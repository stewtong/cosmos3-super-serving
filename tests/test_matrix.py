import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
DRIVER = ROOT / "reproduce" / "run-v1-matrix.py"


class MatrixPlanTests(unittest.TestCase):
    def plan(self, platform):
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run([
                sys.executable, str(DRIVER),
                "--platform", platform,
                "--prompt", "/snapshot/prompt.json",
                "--negative-prompt", "/snapshot/negative.json",
                "--output-root", str(pathlib.Path(directory) / "out"),
            ], text=True, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            return json.loads(completed.stdout)

    def test_b200_plan_has_ten_cells(self):
        value = self.plan("b200")
        self.assertEqual(len(value["cells"]), 10)

    def test_h200_plan_has_seven_cells(self):
        value = self.plan("h200")
        self.assertEqual(len(value["cells"]), 7)


if __name__ == "__main__":
    unittest.main()
