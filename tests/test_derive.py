import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "derive_results_test", ROOT / "reproduce" / "derive-results.py"
)
DERIVE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(DERIVE)


class DeriveTests(unittest.TestCase):
    def test_transport_failure_with_null_output_bytes_stays_in_denominator(self):
        record = {
            "http_status": None,
            "output_bytes": None,
            "technical_valid": False,
            "failure_reason": "TimeoutError",
            "video_validation": None,
            "client_wall_s": 5.0,
        }
        result = DERIVE.aggregate_records([record], {"window_seconds": 5, "node_gpu_count": 8})
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["valid_attempts"], 0)
        self.assertEqual(result["failed_attempts"], 1)
        self.assertEqual(result["video_seconds_per_node_hour"], 0.0)


if __name__ == "__main__":
    unittest.main()
