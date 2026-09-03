import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BENCHMARK = load_module("benchmark", ROOT / "reproduce" / "benchmark.py")


class Response:
    status = 200

    def __init__(self, payload=b"mp4"):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class BenchmarkTests(unittest.TestCase):
    def base_fields(self):
        return {
            **BENCHMARK.DEFAULT_SHAPE,
            "extra_params": "{}",
            "_prompt_sha256": "prompt",
            "_negative_prompt_sha256": "negative",
            "_guardrail": "disabled",
        }

    def test_prompt_files_are_stripped(self):
        with tempfile.TemporaryDirectory() as directory:
            prompt = pathlib.Path(directory) / "prompt"
            negative = pathlib.Path(directory) / "negative"
            prompt.write_text("  prompt text\n", encoding="utf-8")
            negative.write_text("\nnegative text  \n", encoding="utf-8")
            self.assertEqual(
                BENCHMARK.read_prompt(prompt, negative),
                ("prompt text", "negative text"),
            )

    def test_published_hash_constants_are_exact(self):
        self.assertEqual(
            BENCHMARK.EXPECTED_PROMPT_HASHES["prompt"],
            "61c9c4b46b6787d967cc509a2bf323766e70bf5ecf40e09a739362beac135677",
        )
        self.assertEqual(
            BENCHMARK.EXPECTED_PROMPT_HASHES["negative_prompt"],
            "007a1bdfe1ec3edf3b9a71789ca1999a47ad565560f269a3d78bf9a8dfef9cfd",
        )

    def test_prompt_mismatch_requires_new_workload_mode(self):
        with self.assertRaises(ValueError):
            BENCHMARK.check_prompt_hashes("different", "different")
        _hashes, matched = BENCHMARK.check_prompt_hashes(
            "different", "different", allow_new_workload=True
        )
        self.assertFalse(matched)

    def test_seed_cycle_is_per_replica_for_all_topologies(self):
        for replicas in (1, 2, 4, 8):
            seen = {}
            lock = threading.Lock()

            def fake_attempt(_url, fields, _timeout, _clips, attempt_id, replica, kind):
                with lock:
                    seen[attempt_id] = (replica, int(fields["seed"]))
                return {
                    "attempt_id": attempt_id,
                    "started_utc": attempt_id,
                    "replica": replica,
                    "kind": kind,
                }

            BENCHMARK.dispatch_rounds(
                [f"http://r{index}" for index in range(replicas)],
                self.base_fields(),
                24,
                1,
                1,
                "/unused",
                attempt_fn=fake_attempt,
            )
            counts = BENCHMARK.distribute_attempts(24, replicas)
            for replica, count in enumerate(counts):
                for index in range(count):
                    attempt_id = f"production-r{replica}-a{index:03d}"
                    self.assertEqual(seen[attempt_id][1], BENCHMARK.SEEDS[index % 3])

    def test_round_barrier_waits_for_slowest_replica(self):
        starts = {}
        finishes = {}
        lock = threading.Lock()

        def skewed_attempt(_url, _fields, _timeout, _clips, attempt_id, replica, kind):
            with lock:
                starts[attempt_id] = time.monotonic()
            if attempt_id == "production-r0-a000":
                time.sleep(0.05)
            with lock:
                finishes[attempt_id] = time.monotonic()
            return {
                "attempt_id": attempt_id,
                "started_utc": attempt_id,
                "replica": replica,
                "kind": kind,
            }

        _records, rounds = BENCHMARK.dispatch_rounds(
            ["http://r0", "http://r1"],
            self.base_fields(),
            4,
            1,
            1,
            "/unused",
            attempt_fn=skewed_attempt,
        )
        self.assertEqual(len(rounds), 2)
        self.assertGreaterEqual(starts["production-r1-a001"], finishes["production-r0-a000"])

    def test_validation_delay_does_not_change_request_latency(self):
        with tempfile.TemporaryDirectory() as directory:
            fields = self.base_fields()
            fields["seed"] = "17"
            record = BENCHMARK.measure_attempt(
                "http://unused",
                fields,
                1,
                directory,
                "production-r0-a000",
                "r0",
                urlopen=lambda *_args, **_kwargs: Response(),
            )
            request_latency = record["client_wall_s"]
            request_finished = record["finished_utc"]

            def slow_validator(_path):
                time.sleep(0.05)
                return {"valid": True, "errors": []}

            BENCHMARK.validate_records([record], directory, validator=slow_validator)
            self.assertEqual(record["client_wall_s"], request_latency)
            self.assertEqual(record["finished_utc"], request_finished)
            self.assertTrue(record["technical_valid"])

    def test_validation_failure_preserves_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            fields = self.base_fields()
            fields["seed"] = "17"
            record = BENCHMARK.measure_attempt(
                "http://unused", fields, 1, directory,
                "production-r0-a000", "r0",
                urlopen=lambda *_args, **_kwargs: Response(),
            )
            BENCHMARK.validate_records(
                [record], directory,
                validator=lambda _path: {
                    "valid": False,
                    "errors": [{"check": "decode", "detail": "fixture"}],
                },
            )
            self.assertFalse(record["technical_valid"])
            self.assertEqual(record["failure_reason"], "video_invalid:decode")
            self.assertIsNotNone(record["finished_utc"])

    def test_nonempty_output_requires_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            pathlib.Path(directory, "existing").write_text("x", encoding="utf-8")
            with self.assertRaises(ValueError):
                BENCHMARK.prepare_output(directory)

    def test_prompt_check_does_not_create_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            prompt = pathlib.Path(directory) / "prompt"
            negative = pathlib.Path(directory) / "negative"
            output = pathlib.Path(directory) / "unused-output"
            prompt.write_text("different", encoding="utf-8")
            negative.write_text("different", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "reproduce" / "benchmark.py"),
                    "--check-prompts",
                    "--new-workload",
                    "--prompt", str(prompt),
                    "--negative-prompt", str(negative),
                    "--output", str(output),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(output.exists())

    def test_fixture_pipeline_returns_expected_control(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, str(ROOT / "reproduce" / "benchmark.py"),
                 "--fixtures", "--output", str(pathlib.Path(directory) / "fixture")],
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("11 valid, 1 invalid", completed.stdout)

    def test_v2_defaults_to_full_profile_health(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "reproduce" / "benchmark-v2.py"),
             "--profile", "throughput", "--dry-run"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertEqual(output["expected_healthy_replicas"], 8)
        self.assertEqual(output["expected_unavailable_replicas"], 0)

    def test_v2_accepts_explicit_degraded_health_control(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "reproduce" / "benchmark-v2.py"),
             "--profile", "throughput", "--expected-healthy-replicas", "7",
             "--expected-unavailable-replicas", "1", "--dry-run"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertEqual(output["expected_healthy_replicas"], 7)
        self.assertEqual(output["expected_unavailable_replicas"], 1)

    def test_v2_rejects_health_counts_outside_profile_capacity(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "reproduce" / "benchmark-v2.py"),
             "--profile", "throughput", "--expected-healthy-replicas", "7",
             "--expected-unavailable-replicas", "0", "--dry-run"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("sum to the profile capacity", completed.stderr)


if __name__ == "__main__":
    unittest.main()
