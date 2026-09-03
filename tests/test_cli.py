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

    def test_gpu_device_request_quotes_multi_gpu_lists(self):
        self.assertEqual(CLI_MODULE.docker_gpu_device_request([0]), "device=0")
        self.assertEqual(CLI_MODULE.docker_gpu_device_request([0, 1]), '"device=0,1"')
        self.assertEqual(
            CLI_MODULE.docker_gpu_device_request(list(range(8))),
            '"device=0,1,2,3,4,5,6,7"',
        )

    def test_failed_docker_run_removes_created_container_by_exact_label(self):
        config = CLI_MODULE.load_config(CLI_MODULE.DEFAULT_CONFIG)
        with tempfile.TemporaryDirectory() as directory:
            runtime_dir = pathlib.Path(directory) / "runtime"
            args = types.SimpleNamespace(
                runtime_dir=str(runtime_dir),
                profile="latency",
                topology=None,
                platform="h200",
                backend_base_port=None,
                port=None,
                active_requests=1,
                queue_limit=None,
                queue_timeout=None,
                startup_timeout=None,
                guardrails=False,
                cache_dir=str(pathlib.Path(directory) / "cache"),
                dry_run=False,
            )
            docker_ps_results = iter(["created-container-id\n", ""])
            commands = []

            def fake_run(command, **_kwargs):
                commands.append(command)
                if command[:2] == ["docker", "run"]:
                    raise subprocess.CalledProcessError(125, command, stderr="invalid GPU request")
                if command[:3] == ["docker", "ps", "-aq"]:
                    return types.SimpleNamespace(
                        returncode=0, stdout=next(docker_ps_results), stderr=""
                    )
                if command[:3] == ["docker", "rm", "-f"]:
                    return types.SimpleNamespace(returncode=0, stdout="", stderr="")
                raise AssertionError(f"unexpected command: {command}")

            with mock.patch.object(CLI_MODULE, "check_platform"), \
                    mock.patch.object(CLI_MODULE, "assert_ports_free"), \
                    mock.patch.object(CLI_MODULE, "run", side_effect=fake_run):
                with self.assertRaisesRegex(SystemExit, "deployment failed"):
                    CLI_MODULE.serve(config, args)

            launch = next(command for command in commands if command[:2] == ["docker", "run"])
            self.assertEqual(launch[launch.index("--gpus") + 1], '"device=0,1,2,3,4,5,6,7"')
            self.assertIn(["docker", "rm", "-f", "created-container-id"], commands)
            self.assertFalse(CLI_MODULE.runtime_paths(runtime_dir)["state"].exists())

    def test_failed_cleanup_retains_state_for_stop_retry(self):
        config = CLI_MODULE.load_config(CLI_MODULE.DEFAULT_CONFIG)
        with tempfile.TemporaryDirectory() as directory:
            runtime_dir = pathlib.Path(directory) / "runtime"
            args = types.SimpleNamespace(
                runtime_dir=str(runtime_dir),
                profile="latency",
                topology=None,
                platform="h200",
                backend_base_port=None,
                port=None,
                active_requests=1,
                queue_limit=None,
                queue_timeout=None,
                startup_timeout=None,
                guardrails=False,
                cache_dir=str(pathlib.Path(directory) / "cache"),
                dry_run=False,
            )

            def fake_run(command, **_kwargs):
                if command[:2] == ["docker", "run"]:
                    raise subprocess.CalledProcessError(125, command, stderr="launch failed")
                if command[:3] == ["docker", "ps", "-aq"]:
                    return types.SimpleNamespace(
                        returncode=0, stdout="created-container-id\n", stderr=""
                    )
                if command[:3] == ["docker", "rm", "-f"]:
                    return types.SimpleNamespace(
                        returncode=1, stdout="", stderr="removal denied"
                    )
                raise AssertionError(f"unexpected command: {command}")

            with mock.patch.object(CLI_MODULE, "check_platform"), \
                    mock.patch.object(CLI_MODULE, "assert_ports_free"), \
                    mock.patch.object(CLI_MODULE, "run", side_effect=fake_run):
                with self.assertRaisesRegex(
                    SystemExit,
                    "automatic cleanup failed.*deployment state retained",
                ):
                    CLI_MODULE.serve(config, args)

            state_path = CLI_MODULE.runtime_paths(runtime_dir)["state"]
            self.assertTrue(state_path.exists())
            self.assertEqual(CLI_MODULE.read_state(runtime_dir)["phase"], "starting")


if __name__ == "__main__":
    unittest.main()
