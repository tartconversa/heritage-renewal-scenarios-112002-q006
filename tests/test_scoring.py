import tempfile
import unittest
from pathlib import Path

from _path import SRC  # noqa: F401

from renewal_analytics.models import AccessBenefit
from renewal_analytics.scoring import WeightTable, load_weights, score_access

WEIGHT_CSV = (
    "group_code,weight,source,representativeness\n"
    "older,0.6,议事会,常住户样本\n"
    "renter,0.4,议事会,租户样本较小\n"
)


def benefit(service, group, saving):
    return AccessBenefit(
        service_id=service,
        group_code=group,
        minutes_before=None,
        minutes_after=None,
        saving=saving,
        sources=("S-x",),
    )


class ScoringTests(unittest.TestCase):
    def test_no_weights_produces_no_aggregate(self):
        score = score_access(
            (benefit("clinic", "older", 10),),
            None,
            ("older",),
        )
        self.assertFalse(score.available)
        self.assertIsNone(score.aggregate)
        self.assertIn("不生成加权总分", score.note)

    def test_covered_weights_produce_aggregate(self):
        table = WeightTable(
            weights={"older": 0.6, "renter": 0.4},
            source="议事会",
            representativeness="样本有限",
        )
        score = score_access(
            (benefit("clinic", "older", 10), benefit("market", "renter", 20)),
            table,
            ("older", "renter"),
        )
        self.assertTrue(score.available)
        # (10*0.6 + 20*0.4) / 1.0 = 14
        self.assertEqual(score.aggregate, 14.0)
        self.assertIn("价值判断", score.note)

    def test_missing_group_makes_score_unavailable(self):
        table = WeightTable(
            weights={"older": 1.0},
            source="议事会",
            representativeness="仅常住户",
        )
        score = score_access(
            (benefit("clinic", "older", 10), benefit("market", "renter", 20)),
            table,
            ("older", "renter"),
        )
        self.assertFalse(score.available)
        self.assertEqual(score.missing_groups, ("renter",))

    def test_unknown_saving_blocks_aggregate(self):
        table = WeightTable(
            weights={"older": 1.0},
            source="议事会",
            representativeness="样本",
        )
        score = score_access(
            (benefit("clinic", "older", None),),
            table,
            ("older",),
        )
        self.assertFalse(score.available)
        self.assertIsNone(score.aggregate)

    def test_load_weights_rejects_negative_and_missing_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.csv"
            path.write_text(
                "group_code,weight\nolder,-1\n", encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                load_weights(path)

            path.write_text("group_code,weight\nolder,1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_weights(path)

    def test_load_weights_roundtrip_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.csv"
            path.write_text(WEIGHT_CSV, encoding="utf-8")
            table = load_weights(path)
            self.assertEqual(table.weights, {"older": 0.6, "renter": 0.4})
            self.assertIn("议事会", table.source)
            self.assertIn("租户样本较小", table.representativeness)


if __name__ == "__main__":
    unittest.main()
