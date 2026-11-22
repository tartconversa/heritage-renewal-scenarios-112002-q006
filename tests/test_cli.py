import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _path import SRC  # noqa: F401

from fixtures import write_dataset

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        # -I 隔离模式会忽略 PYTHONPATH，因此用 sitecustomize 之外的简单办法：
        # 通过 -c 先把 src 注入 sys.path 再以 __main__ 方式运行包。
        bootstrap = (
            "import runpy, sys; "
            f"sys.path.insert(0, {str(ROOT / 'src')!r}); "
            "runpy.run_module('renewal_analytics', run_name='__main__')"
        )
        env_cmd = [sys.executable, "-I", "-c", bootstrap, *args]
        return subprocess.run(
            env_cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin:/opt/ccusr/task-python/bin"},
        )

    def test_validate_and_assess_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = write_dataset(Path(tmp) / "data")
            out_dir = Path(tmp) / "reports"
            result = self._run(
                "validate", "--data", str(data_dir)
            )
            # fixtures 含悬空引用与倒置成本，validate 应返回 2
            self.assertEqual(result.returncode, 2, result.stderr)

            # 清理为干净数据后 assess 成功并产出两个报告文件
            (data_dir / "proposals.csv").write_text(
                "proposal_id,building_id,work,estimate_low,estimate_high,operator_id\n"
                "S-1,B-1,access,180000,260000,OP-1\n"
                "S-2,B-2,repair,220000,280000,\n"
                "S-3,B-3,repair,310000,390000,OP-2\n",
                encoding="utf-8",
            )
            (data_dir / "access-links.csv").write_text(
                "proposal_id,service_id,group_code,minutes_before,minutes_after\n"
                "S-1,clinic,older,24,12\n"
                "S-3,daycare,caregiver,31,19\n",
                encoding="utf-8",
            )
            result = self._run(
                "assess", "--data", str(data_dir),
                "--out", str(out_dir),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            reports = list(out_dir.glob("*-report.md"))
            jsons = list(out_dir.glob("*-result.json"))
            self.assertEqual(len(reports), 1)
            self.assertEqual(len(jsons), 1)

            payload = json.loads(jsons[0].read_text(encoding="utf-8"))
            self.assertIn("proposal_assessments", payload)
            self.assertIn("snapshot", payload)
            md = reports[0].read_text(encoding="utf-8")
            self.assertIn("保护可行性裁决", md)
            self.assertIn("价值判断边界", md)

    def test_blocking_errors_abort_assessment(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = write_dataset(Path(tmp) / "data")
            result = self._run(
                "assess", "--data", str(data_dir),
                "--out", str(Path(tmp) / "reports"),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("阻断性错误", result.stderr)


if __name__ == "__main__":
    unittest.main()
