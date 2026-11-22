import tempfile
import unittest
from pathlib import Path

from _path import SRC  # noqa: F401

from renewal_analytics.assessment import assess_dataset
from renewal_analytics.loader import load_dataset
from renewal_analytics.models import CapacityState, Verdict
from renewal_analytics.snapshot import take_snapshot

from fixtures import write_dataset


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # 评估使用无阻断错误的数据：移除悬空引用与倒置成本方案
        overrides = {
            "proposals.csv": (
                "proposal_id,building_id,work,estimate_low,estimate_high,operator_id\n"
                "S-1,B-1,access,180000,260000,OP-1\n"
                "S-2,B-2,repair,220000,280000,\n"
                "S-3,B-3,repair,310000,390000,OP-2\n"
                "S-4,B-1,demolish,100000,150000,OP-1\n"
                "S-8,B-2,access,,120000,OP-1\n"
            ),
            "access-links.csv": (
                "proposal_id,service_id,group_code,minutes_before,minutes_after\n"
                "S-1,clinic,older,24,12\n"
                "S-1,market,renter,18,10\n"
                "S-3,daycare,caregiver,31,19\n"
                "S-8,clinic,older,24,9\n"
            ),
            "operations.csv": (
                "operator_id,service_id,capacity_per_day,confirmed_start\n"
                "OP-1,community_room,35,2027-04-01\n"
                "OP-2,clinic,18,\n"
            ),
        }
        self.data_dir = write_dataset(self._tmp.name, overrides)
        self.dataset = load_dataset(self.data_dir)
        self.snapshot = take_snapshot(self.data_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def test_vetoed_proposal_has_no_score_but_kept_in_results(self):
        result = assess_dataset(self.dataset, self.snapshot)
        s4 = next(
            a for a in result.proposal_assessments
            if a.proposal.proposal_id == "S-4"
        )
        self.assertIs(s4.feasibility.verdict, Verdict.INFEASIBLE)
        self.assertIsNone(s4.score)  # 保护底线不参与加权

    def test_combination_deduplicates_shared_access_link(self):
        result = assess_dataset(self.dataset, self.snapshot)
        combo = next(
            c for c in result.combinations
            if set(c.member_ids) == {"S-1", "S-8"}
        )
        clinic = next(
            b for b in combo.access
            if b.service_id == "clinic" and b.group_code == "older"
        )
        self.assertEqual(clinic.minutes_after, 9)
        self.assertEqual(clinic.saving, 15)
        self.assertEqual(len(combo.shared_links), 1)
        self.assertEqual(sorted(clinic.sources), ["S-1", "S-8"])

    def test_combination_cost_ranges_sum_and_keep_unknown_side(self):
        result = assess_dataset(self.dataset, self.snapshot)
        combo = next(
            c for c in result.combinations
            if set(c.member_ids) == {"S-1", "S-8"}
        )
        # S-8 缺 estimate_low，因此合计 low 只含 S-1，且 complete=False
        self.assertEqual(combo.cost_low, 180000)
        self.assertEqual(combo.cost_high, 260000 + 120000)
        self.assertFalse(combo.cost_complete)

    def test_combination_with_vetoed_member_is_infeasible(self):
        result = assess_dataset(self.dataset, self.snapshot)
        combo = next(
            c for c in result.combinations
            if "S-4" in c.member_ids
        )
        self.assertFalse(combo.feasible)
        self.assertTrue(combo.infeasible_reasons)
        self.assertIsNone(combo.score)

    def test_stable_capacity_only_counts_confirmed_lines(self):
        result = assess_dataset(self.dataset, self.snapshot)
        s3 = next(
            a for a in result.proposal_assessments
            if a.proposal.proposal_id == "S-3"
        )
        self.assertFalse(
            any(c.state is CapacityState.STABLE for c in s3.capacity_lines)
        )

    def test_demand_trace_links_groups_to_protection_and_cost(self):
        result = assess_dataset(self.dataset, self.snapshot)
        trace = next(
            t for t in result.demand_traces
            if t.group_code == "older" and t.service_id == "clinic"
        )
        self.assertEqual(trace.proposal_ids, ("S-1", "S-8"))
        self.assertEqual(trace.best_after_minutes, 9)
        # 保护边界保留建筑等级与许可范围
        self.assertTrue(
            any(bid == "B-1" and level == "high"
                for bid, level, _ in trace.protection_boundaries)
        )
        # 追溯链的容量行只允许是该服务或运营缺口，不能串到其他服务
        self.assertTrue(
            all(c.service_id == "clinic" or c.service_id is None
                for c in trace.capacity_lines)
        )

    def test_group_matrix_distinguishes_zero_from_unknown(self):
        result = assess_dataset(self.dataset, self.snapshot)
        row_s2 = result.group_matrix["S-2"]
        self.assertTrue(all(v == 0 for v in row_s2.values()))  # 无改善


if __name__ == "__main__":
    unittest.main()
