import tempfile
import unittest
from pathlib import Path

from _path import SRC  # noqa: F401  (sys.path 引导)

from renewal_analytics.loader import LoaderError, has_blocking_errors, load_dataset
from renewal_analytics.models import IssueLevel

from fixtures import write_dataset


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = write_dataset(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_cells_become_none_not_zero(self):
        dataset = load_dataset(self.data_dir)
        s2 = dataset.proposals_by_id["S-2"]
        self.assertIsNone(s2.operator_id)
        s8 = dataset.proposals_by_id["S-8"]
        self.assertIsNone(s8.estimate_low)  # 未知，不是 0
        self.assertEqual(s8.estimate_high, 120000)

    def test_semicolon_fields_split_to_tuple(self):
        dataset = load_dataset(self.data_dir)
        self.assertEqual(
            dataset.buildings_by_id["B-1"].permitted_work,
            ("facade", "access"),
        )

    def test_dangling_reference_and_inverted_range_are_errors(self):
        dataset = load_dataset(self.data_dir)
        codes = {(i.level, i.code) for i in dataset.issues}
        self.assertIn((IssueLevel.ERROR, "dangling_reference"), codes)
        self.assertIn((IssueLevel.ERROR, "inverted_cost_range"), codes)
        self.assertTrue(has_blocking_errors(dataset))

    def test_incomplete_cost_is_warning(self):
        dataset = load_dataset(self.data_dir)
        self.assertTrue(
            any(
                i.level is IssueLevel.WARNING and i.code == "incomplete_cost"
                for i in dataset.issues
            )
        )

    def test_missing_file_raises_loader_error(self):
        (self.data_dir / "buildings.csv").unlink()
        with self.assertRaises(LoaderError):
            load_dataset(self.data_dir)

    def test_missing_column_raises_loader_error(self):
        broken = (
            "building_id,block,protection_level,condition\n"
            "B-1,Old-A,high,poor\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            write_dataset(tmp, {"buildings.csv": broken})
            with self.assertRaises(LoaderError):
                load_dataset(tmp)


if __name__ == "__main__":
    unittest.main()
