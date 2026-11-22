import tempfile
import unittest

from _path import SRC  # noqa: F401

from renewal_analytics.feasibility import check_combination, check_proposal
from renewal_analytics.loader import load_dataset
from renewal_analytics.models import Verdict

from fixtures import write_dataset


class FeasibilityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dataset = load_dataset(write_dataset(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_permitted_work_passes(self):
        check = check_proposal(self.dataset.proposals_by_id["S-1"], self.dataset)
        self.assertIs(check.verdict, Verdict.FEASIBLE)

    def test_work_outside_permitted_scope_is_vetoed(self):
        check = check_proposal(self.dataset.proposals_by_id["S-4"], self.dataset)
        self.assertIs(check.verdict, Verdict.INFEASIBLE)
        self.assertTrue(any("许可范围" in r for r in check.reasons))

    def test_building_without_any_permitted_work_is_vetoed(self):
        check = check_proposal(self.dataset.proposals_by_id["S-5"], self.dataset)
        self.assertIs(check.verdict, Verdict.INFEASIBLE)

    def test_missing_building_is_vetoed(self):
        check = check_proposal(self.dataset.proposals_by_id["S-6"], self.dataset)
        self.assertIs(check.verdict, Verdict.INFEASIBLE)

    def test_combination_requires_every_member_to_pass(self):
        check = check_combination(("S-1", "S-4"), self.dataset)
        self.assertIs(check.verdict, Verdict.INFEASIBLE)
        self.assertTrue(any("[S-4]" in r for r in check.reasons))

    def test_combination_of_feasible_members_passes(self):
        check = check_combination(("S-1", "S-3"), self.dataset)
        self.assertIs(check.verdict, Verdict.FEASIBLE)


if __name__ == "__main__":
    unittest.main()
