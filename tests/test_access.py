import tempfile
import unittest

from _path import SRC  # noqa: F401

from renewal_analytics.access import (
    merge_access,
    proposal_access,
    total_saving,
    worsening_issues,
)
from renewal_analytics.loader import load_dataset
from renewal_analytics.models import AccessLink, IssueLevel

from fixtures import write_dataset


def link(pid, service, group, before, after):
    return AccessLink(
        proposal_id=pid,
        service_id=service,
        group_code=group,
        minutes_before=before,
        minutes_after=after,
    )


class AccessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dataset = load_dataset(write_dataset(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_single_proposal_benefit(self):
        benefits = proposal_access(
            self.dataset.links_by_proposal["S-1"]
        )
        by_key = {(b.service_id, b.group_code): b for b in benefits}
        self.assertEqual(by_key[("clinic", "older")].saving, 12)
        self.assertEqual(by_key[("market", "renter")].saving, 8)
        self.assertEqual(by_key[("clinic", "older")].sources, ("S-1",))

    def test_merge_deduplicates_shared_link_keeps_best_after(self):
        links = (
            link("S-1", "clinic", "older", 24, 12),
            link("S-8", "clinic", "older", 24, 9),
        )
        benefits, shared = merge_access(links)
        self.assertEqual(len(benefits), 1)
        benefit = benefits[0]
        self.assertEqual(benefit.minutes_after, 9)  # 取最优
        self.assertEqual(benefit.minutes_before, 24)  # 基准取最差现状
        self.assertEqual(benefit.saving, 15)
        self.assertEqual(shared[0][0:2], ("clinic", "older"))
        self.assertEqual(sorted(shared[0][2]), ["S-1", "S-8"])

    def test_missing_minutes_keeps_saving_unknown(self):
        benefits = proposal_access(
            self.dataset.links_by_proposal["S-3"]
        )
        unknown = [b for b in benefits if b.service_id == "clinic"][0]
        self.assertIsNone(unknown.saving)
        self.assertIn("缺失", unknown.note)
        self.assertIsNone(total_saving(benefits))

    def test_worsening_is_flagged_not_silently_flipped(self):
        benefits = proposal_access(
            self.dataset.links_by_proposal["S-7"]
        )
        issues = worsening_issues(benefits)
        self.assertEqual(len(issues), 1)
        self.assertIs(issues[0].level, IssueLevel.WARNING)
        self.assertEqual(issues[0].code, "access_worsening")
        # 恶化时 saving 为负值，原样保留
        self.assertEqual(benefits[0].saving, -7)

    def test_no_links_total_saving_is_zero(self):
        self.assertEqual(total_saving(()), 0)


if __name__ == "__main__":
    unittest.main()
