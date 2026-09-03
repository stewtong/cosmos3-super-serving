import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
RENDERER = ROOT / "reproduce" / "render-benchmarks.py"


class RenderBenchmarkTests(unittest.TestCase):
    def test_committed_document_matches_records(self):
        completed = subprocess.run(
            [sys.executable, str(RENDERER), "--check"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("17 cells, 408/408", completed.stdout)

    def test_planted_table_drift_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "BENCHMARKS.md"
            output.write_text("changed", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(RENDERER), "--check", "--output", str(output)],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("drift", completed.stderr)

    def test_all_primary_cell_ids_are_rendered(self):
        text = (ROOT / "BENCHMARKS.md").read_text(encoding="utf-8")
        for cell in (
            "T1_1x8", "T2_2x4", "T3_4x2", "T4_8x1",
            "T1C2", "T2C2", "T3C2", "T4C2", "T1R", "T1C2R",
            "H1_1x8", "H2_2x4", "H3_4x2", "H4_8x1", "H2C2", "H3C2", "H1R",
        ):
            self.assertIn(f"`{cell}`", text)


if __name__ == "__main__":
    unittest.main()
