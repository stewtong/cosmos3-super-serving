import json
import contextlib
import io
import importlib.util
import pathlib
import subprocess
import tempfile
import types
import unittest
from importlib.machinery import SourceFileLoader
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "cosmos3-super"


def load_cli():
    loader = SourceFileLoader("cosmos3_super_cli", str(CLI))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


CLI_MODULE = load_cli()


class CliDryRunTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [str(CLI), *arguments],
            text=True,
            capture_output=True,
        )

    def test_every_profile_resolves_on_both_platforms(self):
        expected = {"latency": "1x8", "balanced": "4x2", "throughput": "8x1"}
        for platform in ("b200", "h200"):
            for profile, topology in expected.items():
                completed = self.run_cli(
                    "serve", "--platform", platform, "--profile", profile, "--dry-run"
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                value = json.loads(completed.stdout)
                self.assertEqual(value["topology"], topology)
                self.assertEqual(value["replicas"] * value["gpus_per_replica"], 8)
                self.assertEqual(value["active_requests_per_replica"], 1)
                self.assertTrue(value["benchmark_backed_admission"])

    def test_explicit_two_by_four_override_remains_available(self):
        completed = self.run_cli(
            "serve", "--platform", "b200", "--topology", "2x4", "--dry-run"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        value = json.loads(completed.stdout)
        self.assertEqual(value["profile"], "custom")
        self.assertEqual(value["gpu_groups"], [[0, 1, 2, 3], [4, 5, 6, 7]])
        self.assertEqual(value["backend_ports"], [8100, 8101])

    def test_profile_and_topology_are_mutually_exclusive(self):
        completed = self.run_cli(
            "serve", "--platform", "b200", "--profile", "latency",
            "--topology", "1x8", "--dry-run",
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("choose --profile or --topology", completed.stderr)

    def test_front_door_cannot_overlap_backends(self):
        completed = self.run_cli(
            "serve", "--platform", "b200", "--profile", "throughput",
            "--port", "8100", "--dry-run",
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("overlaps", completed.stderr)

    def test_stop_removes_only_exact_label_results(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime_dir = pathlib.Path(directory)
            state_path = CLI_MODULE.runtime_paths(runtime_dir)["state"]
            CLI_MODULE.write_json(state_path, {
                "run_id": "owned-run",
                "router_pid": 1234,
            })
            calls = []

            def fake_run(command, **_kwargs):
                calls.append(command)
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")

            args = types.SimpleNamespace(runtime_dir=str(runtime_dir), dry_run=False)
            with mock.patch.object(CLI_MODULE, "docker_ids", return_value=["exact-container-id"]), \
                    mock.patch.object(CLI_MODULE, "router_process_matches", return_value=False), \
                    mock.patch.object(CLI_MODULE, "run", side_effect=fake_run), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                result = CLI_MODULE.stop(None, args)
            self.assertEqual(result, 0)
            self.assertEqual(calls, [["docker", "rm", "-f", "exact-container-id"]])
            self.assertFalse(state_path.exists())


if __name__ == "__main__":
    unittest.main()
