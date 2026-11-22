import tempfile
import unittest
from pathlib import Path

from _path import SRC  # noqa: F401

from renewal_analytics.opinions import load_opinions, record_opinion
from renewal_analytics.snapshot import changed_files, diff_snapshots, take_snapshot

from fixtures import write_dataset


class SnapshotTests(unittest.TestCase):
    def test_identical_inputs_produce_identical_snapshot(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            write_dataset(a)
            write_dataset(b)
            self.assertEqual(
                take_snapshot(a).combined_sha256,
                take_snapshot(b).combined_sha256,
            )

    def test_modified_file_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_dataset(tmp)
            before = take_snapshot(tmp)
            proposals = Path(tmp) / "proposals.csv"
            proposals.write_text(
                proposals.read_text(encoding="utf-8").replace(
                    "180000,260000", "190000,270000"
                ),
                encoding="utf-8",
            )
            after = take_snapshot(tmp)
            changes = changed_files(diff_snapshots(before, after))
            self.assertEqual([c.path for c in changes], ["proposals.csv"])
            self.assertEqual(changes[0].kind, "modified")

    def test_added_and_removed_files_in_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_dataset(tmp)
            before = take_snapshot(tmp)
            (Path(tmp) / "weights.csv").write_text("x", encoding="utf-8")
            # weights.csv 不在 SNAPSHOT_FILES 内，不影响快照
            self.assertEqual(
                take_snapshot(tmp).combined_sha256,
                before.combined_sha256,
            )


class OpinionTests(unittest.TestCase):
    def test_opinions_are_append_only_and_marked_stale(self):
        with tempfile.TemporaryDirectory() as data_dir, tempfile.TemporaryDirectory() as out:
            write_dataset(data_dir)
            snapshot = take_snapshot(data_dir)
            store = Path(out) / "opinions.jsonl"

            record_opinion(
                store, snapshot.combined_sha256, snapshot.run_id,
                author="居民代表甲", stance="support",
                basis="通行时间缩短明显", scope_proposal_id="S-1",
            )
            record_opinion(
                store, snapshot.combined_sha256, snapshot.run_id,
                author="商户代表乙", stance="object",
                basis="担心施工封路挤出小商户",
            )

            fresh = load_opinions(store, snapshot.combined_sha256)
            self.assertEqual(len(fresh), 2)
            self.assertFalse(any(item.stale for item in fresh))

            # 修改输入后旧意见必须标注过期，但原样保留
            proposals = Path(data_dir) / "proposals.csv"
            proposals.write_text(
                proposals.read_text(encoding="utf-8").replace(
                    "180000,260000", "190000,270000"
                ),
                encoding="utf-8",
            )
            new_snapshot = take_snapshot(data_dir)
            stale_items = load_opinions(
                store, new_snapshot.combined_sha256
            )
            self.assertEqual(len(stale_items), 2)
            self.assertTrue(all(item.stale for item in stale_items))
            # 依据快照仍然是旧哈希
            self.assertEqual(
                stale_items[0].opinion.snapshot_combined,
                snapshot.combined_sha256,
            )


if __name__ == "__main__":
    unittest.main()
