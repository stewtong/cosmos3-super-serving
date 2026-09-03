import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class ClaimReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.b200 = read_json(ROOT / "results" / "b200-single-node-20260831.json")
        self.h200 = read_json(ROOT / "results" / "h200-single-node-20260831.json")
        self.runtime_validation = read_json(
            ROOT / "results" / "runtime-validation-20260903.json"
        )
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.method = (ROOT / "reproduce" / "METHOD.md").read_text(encoding="utf-8")

    def test_primary_census_matches_documents(self):
        cells = len(self.b200["cells"]) + len(self.h200["cells"])
        attempts = sum(
            cell["derived"]["attempts"]
            for document in (self.b200, self.h200)
            for cell in document["cells"].values()
        )
        valid = sum(
            cell["derived"]["valid_attempts"]
            for document in (self.b200, self.h200)
            for cell in document["cells"].values()
        )
        self.assertEqual((cells, attempts, valid), (17, 408, 408))
        for value in ("17", "408"):
            self.assertIn(value, self.readme)
            self.assertIn(value, self.method)

    def test_profile_values_trace_to_primary_cells(self):
        pairs = (
            (self.b200, "T1_1x8"),
            (self.b200, "T3_4x2"),
            (self.b200, "T4_8x1"),
            (self.h200, "H1_1x8"),
            (self.h200, "H3_4x2"),
            (self.h200, "H4_8x1"),
        )
        for document, cell_name in pairs:
            derived = document["cells"][cell_name]["derived"]
            self.assertIn(f"{derived['mean_client_wall_s']:.1f} s", self.readme)
            self.assertIn(f"{derived['video_seconds_per_node_hour']:.1f}", self.readme)

    def test_pins_and_hashes_match_method(self):
        for value in (
            "e0262be9d8f7586bc24c069a2aed2b665bdff266",
            "sha256:6d2630c7d637b699557573f2c3fee8df5d4d0cd718977aa22549ed6a6ef30587",
            self.b200["prompt_hashes"]["anchor"],
            self.b200["prompt_hashes"]["negative"],
        ):
            self.assertIn(value, self.method)

    def test_throughput_claim_is_bounded(self):
        self.assertIn(
            "Highest node throughput among the four measured topologies for the pinned workload",
            self.readme,
        )
        self.assertNotIn(" optimal ", self.readme.lower())
        self.assertNotIn(" best ", self.readme.lower())

    def test_runtime_validation_record_is_operability_only(self):
        record = self.runtime_validation
        self.assertEqual(record["result"], "pass")
        self.assertIn("not performance evidence", record["scope"])
        self.assertEqual(
            {
                name: value["topology"]
                for name, value in record["profiles"].items()
            },
            {"latency": "1x8", "balanced": "4x2", "throughput": "8x1"},
        )
        self.assertEqual(
            record["controls"]["bounded_admission"]["request_17_http_status"],
            429,
        )
        self.assertEqual(
            record["controls"]["unhealthy_replica"]["healthy_after"], 7
        )
        encoded = json.dumps(record, sort_keys=True)
        for forbidden in (
            "window_seconds", "client_wall_s", "server_generation_s",
            "computeinstance-", "/var/tmp/", "/data/", "router_pid",
        ):
            self.assertNotIn(forbidden, encoded)


if __name__ == "__main__":
    unittest.main()
