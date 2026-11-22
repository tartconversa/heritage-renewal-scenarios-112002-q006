import tempfile
import unittest

from _path import SRC  # noqa: F401

from renewal_analytics.access import proposal_access
from renewal_analytics.capacity import (
    capacity_lines_for,
    merge_capacity,
    service_coverage,
    stable_capacity_total,
)
from renewal_analytics.loader import load_dataset
from renewal_analytics.models import CapacityState

from fixtures import write_dataset


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dataset = load_dataset(write_dataset(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_confirmed_operator_counts_as_stable(self):
        lines = capacity_lines_for(
            self.dataset.proposals_by_id["S-1"], self.dataset
        )
        self.assertEqual(len(lines), 1)
        self.assertIs(lines[0].state, CapacityState.STABLE)
        self.assertEqual(stable_capacity_total(lines), 35)

    def test_missing_confirmed_start_is_unconfirmed(self):
        lines = capacity_lines_for(
            self.dataset.proposals_by_id["S-3"], self.dataset
        )
        self.assertIs(lines[0].state, CapacityState.UNCONFIRMED)
        self.assertEqual(lines[0].capacity_per_day, 18)
        self.assertEqual(stable_capacity_total(lines), 0)  # 不计入稳定容量

    def test_no_operator_means_capacity_cannot_count(self):
        lines = capacity_lines_for(
            self.dataset.proposals_by_id["S-2"], self.dataset
        )
        self.assertIs(lines[0].state, CapacityState.NO_OPERATOR)
        self.assertIsNone(lines[0].capacity_per_day)

    def test_merge_deduplicates_same_operator_service(self):
        first = capacity_lines_for(
            self.dataset.proposals_by_id["S-1"], self.dataset
        )
        merged = merge_capacity(first + first)
        self.assertEqual(len(merged), 1)

    def test_service_coverage_flags_mismatch(self):
        all_access = tuple(
            benefit
            for pid in ("S-1", "S-3")
            for benefit in proposal_access(
                self.dataset.links_by_proposal.get(pid, ())
            )
        )
        coverage = {c.service_id: c for c in
                    service_coverage(self.dataset, all_access)}
        # daycare 有可达改善但无任何运营承诺
        self.assertTrue(coverage["daycare"].mismatch_notes)
        # community_room 有容量但无可达改善
        self.assertTrue(coverage["community_room"].mismatch_notes)


if __name__ == "__main__":
    unittest.main()
