#!/usr/bin/env python3
"""Derive strict technical-validity and throughput aggregates from result records."""
import argparse
import json
import os
import statistics
import sys
from datetime import datetime

SECONDS_PER_CLIP = 7.875


def percentile_nearest_rank(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, int(len(ordered) * fraction + 0.999999999))
    return round(ordered[rank - 1], 3)


def parse_utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def strict_valid(record):
    return (
        record.get("http_status") == 200
        and record.get("output_bytes", 0) > 0
        and record.get("technical_valid") is True
        and record.get("failure_reason") is None
        and isinstance(record.get("video_validation"), dict)
        and record["video_validation"].get("valid") is True
    )


def aggregate_records(records, window):
    if "window_seconds" in window:
        window_seconds = float(window["window_seconds"])
    elif window.get("window_start_utc") and window.get("window_end_utc"):
        window_seconds = (parse_utc(window["window_end_utc"]) - parse_utc(window["window_start_utc"])).total_seconds()
    else:
        raise ValueError("window needs window_seconds or start and end timestamps")
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    valid = [record for record in records if strict_valid(record)]
    latency = [float(record["client_wall_s"]) for record in valid]
    attempted = len(records)
    video_seconds = len(valid) * SECONDS_PER_CLIP
    node_rate = video_seconds * 3600 / window_seconds
    gpu_count = int(window.get("node_gpu_count", 8))
    return {
        "attempts": attempted,
        "valid_attempts": len(valid),
        "failed_attempts": attempted - len(valid),
        "yield_technical_validity": round(len(valid) / attempted, 4) if attempted else None,
        "median_client_wall_s": round(statistics.median(latency), 3) if latency else None,
        "mean_client_wall_s": round(statistics.mean(latency), 3) if latency else None,
        "min_client_wall_s": round(min(latency), 3) if latency else None,
        "max_client_wall_s": round(max(latency), 3) if latency else None,
        "p95_client_wall_s": percentile_nearest_rank(latency, 0.95),
        "window_seconds": round(window_seconds, 6),
        "video_seconds": round(video_seconds, 3),
        "video_seconds_per_node_hour": round(node_rate, 1),
        "video_seconds_per_gpu_hour": round(node_rate / gpu_count, 1),
    }


def read_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def aggregate(requests_path, window_path):
    with open(window_path, encoding="utf-8") as handle:
        window = json.load(handle)
    return aggregate_records(read_jsonl(requests_path), window)


def verify_embedded(path):
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    if "cells" not in document:
        # An observational summary carries no per-attempt inputs, so there is nothing
        # to recompute. Say so rather than returning an empty pass, which reads as
        # "checked and correct" when nothing was checked.
        return None
    failures = []
    for name, cell in document.get("cells", {}).items():
        derived = aggregate_records(cell["attempts"], cell["window"])
        published = cell["derived"]
        if derived != published:
            failures.append({"cell": name, "published": published, "rederived": derived})
    if document.get("comparison_basis") == "b200_topology":
        cells = document["cells"]
        d = {name: cell["derived"] for name, cell in cells.items()}
        baseline_rate = d["T1_1x8"]["video_seconds_per_node_hour"]
        baseline_latency = d["T1_1x8"]["median_client_wall_s"]
        computed = {
            "throughput_gain_vs_T1_pct": {
                name: round((d[name]["video_seconds_per_node_hour"] / baseline_rate - 1) * 100, 1)
                for name in ("T2_2x4", "T3_4x2", "T4_8x1")
            },
            "latency_ratio_vs_T1": {
                name: round(d[name]["median_client_wall_s"] / baseline_latency, 2)
                for name in ("T2_2x4", "T3_4x2", "T4_8x1")
            },
            "cost_per_video_second_reduction_vs_T1_pct": {
                name: round((1 - baseline_rate / d[name]["video_seconds_per_node_hour"]) * 100, 1)
                for name in ("T2_2x4", "T3_4x2", "T4_8x1")
            },
            "concurrency_two": {
                "T1_throughput_delta_pct": round((d["T1C2"]["video_seconds_per_node_hour"] / baseline_rate - 1) * 100, 1),
                "T1_median_latency_delta_pct": round((d["T1C2"]["median_client_wall_s"] / baseline_latency - 1) * 100, 1),
                "T4_throughput_delta_pct": round((d["T4C2"]["video_seconds_per_node_hour"] / d["T4_8x1"]["video_seconds_per_node_hour"] - 1) * 100, 1),
                "T4_median_latency_delta_pct": round((d["T4C2"]["median_client_wall_s"] / d["T4_8x1"]["median_client_wall_s"] - 1) * 100, 1),
                # Both concurrency-two cells are bimodal. On T4C2 the split is uneven
                # (sixteen fast attempts, eight slow), so the median lands inside the
                # fast group and understates the cost. The mean is the figure to use.
                "T1_mean_latency_delta_pct": round((d["T1C2"]["mean_client_wall_s"] / d["T1_1x8"]["mean_client_wall_s"] - 1) * 100, 2),
                "T4_mean_latency_delta_pct": round((d["T4C2"]["mean_client_wall_s"] / d["T4_8x1"]["mean_client_wall_s"] - 1) * 100, 2),
            },
            "drift_mean_delta_vs_T1_pct": round((d["T1DRIFT"]["mean_client_wall_s"] / d["T1_1x8"]["mean_client_wall_s"] - 1) * 100, 1),
        }
        if computed != document.get("comparisons"):
            failures.append({"comparison": "b200_topology", "published": document.get("comparisons"), "rederived": computed})
    if document.get("comparison_basis") == "b200_single_node_20260831":
        d = {name: cell["derived"] for name, cell in document["cells"].items()}
        rate = lambda name: d[name]["video_seconds_per_node_hour"]
        mean = lambda name: d[name]["mean_client_wall_s"]
        # Two decimals on this basis, not one: the delayed-repeat deltas are around a
        # tenth of a percent, and one decimal would not resolve them.
        delta = lambda a, b: round((a / b - 1) * 100, 2)
        pairs = (("T1_1x8", "T1C2"), ("T2_2x4", "T2C2"), ("T3_4x2", "T3C2"), ("T4_8x1", "T4C2"))
        others = ("T2_2x4", "T3_4x2", "T4_8x1")
        computed = {
            "concurrency_two_throughput_delta_pct": {
                base: delta(rate(conc), rate(base)) for base, conc in pairs
            },
            "concurrency_two_mean_latency_delta_pct": {
                base: delta(mean(conc), mean(base)) for base, conc in pairs
            },
            "within_node_repeat_delta_pct": {
                "T1R_vs_T1_throughput": delta(rate("T1R"), rate("T1_1x8")),
                "T1R_vs_T1_mean_latency": delta(mean("T1R"), mean("T1_1x8")),
                "T1C2R_vs_T1C2_throughput": delta(rate("T1C2R"), rate("T1C2")),
                "T1C2R_vs_T1C2_mean_latency": delta(mean("T1C2R"), mean("T1C2")),
            },
            "throughput_gain_vs_T1_pct": {
                name: delta(rate(name), rate("T1_1x8")) for name in others
            },
            "latency_ratio_vs_T1": {
                name: round(mean(name) / mean("T1_1x8"), 2) for name in others
            },
            "cost_per_video_second_reduction_vs_T1_pct": {
                name: round((1 - rate("T1_1x8") / rate(name)) * 100, 2) for name in others
            },
        }
        if computed != document.get("comparisons"):
            failures.append({"comparison": "b200_single_node", "published": document.get("comparisons"), "rederived": computed})
    if document.get("comparison_basis") == "h200_single_node_20260831":
        d = {name: cell["derived"] for name, cell in document["cells"].items()}
        rate = lambda name: d[name]["video_seconds_per_node_hour"]
        mean = lambda name: d[name]["mean_client_wall_s"]
        delta = lambda a, b: round((a / b - 1) * 100, 2)
        pairs = (("H2_2x4", "H2C2"), ("H3_4x2", "H3C2"))
        others = ("H2_2x4", "H3_4x2", "H4_8x1")
        computed = {
            "concurrency_two_throughput_delta_pct": {
                base: delta(rate(conc), rate(base)) for base, conc in pairs
            },
            "concurrency_two_mean_latency_delta_pct": {
                base: delta(mean(conc), mean(base)) for base, conc in pairs
            },
            "within_node_repeat_delta_pct": {
                "H1R_vs_H1_throughput": delta(rate("H1R"), rate("H1_1x8")),
                "H1R_vs_H1_mean_latency": delta(mean("H1R"), mean("H1_1x8")),
            },
            "throughput_gain_vs_H1_pct": {
                name: delta(rate(name), rate("H1_1x8")) for name in others
            },
            "latency_ratio_vs_H1": {
                name: round(mean(name) / mean("H1_1x8"), 2) for name in others
            },
            "cost_per_video_second_reduction_vs_H1_pct": {
                name: round((1 - rate("H1_1x8") / rate(name)) * 100, 2) for name in others
            },
        }
        # The cross-platform block is the point of this record, so it is recomputed
        # against the matched B200 file rather than trusted. Both sides are the mean
        # and the node rate from the same single-node basis; comparing against any
        # other B200 record would break the control this pair rests on.
        basis = document.get("cross_platform_control", {}).get("basis")
        if basis:
            other_path = os.path.join(os.path.dirname(os.path.abspath(path)), os.path.basename(basis))
            with open(other_path, encoding="utf-8") as handle:
                bd = {name: cell["derived"] for name, cell in json.load(handle)["cells"].items()}
            paired = {"H1_1x8": "T1_1x8", "H2_2x4": "T2_2x4", "H3_4x2": "T3_4x2", "H4_8x1": "T4_8x1"}
            computed["cross_platform_vs_b200_single_node"] = {
                "mean_latency_ratio": {
                    h: round(mean(h) / bd[t]["mean_client_wall_s"], 2) for h, t in paired.items()
                },
                "node_throughput_share_pct": {
                    h: round(rate(h) / bd[t]["video_seconds_per_node_hour"] * 100, 2) for h, t in paired.items()
                },
            }
        if computed != document.get("comparisons"):
            failures.append({"comparison": "h200_single_node", "published": document.get("comparisons"), "rederived": computed})
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requests", nargs="?")
    parser.add_argument("window", nargs="?")
    parser.add_argument("--verify-embedded", metavar="RESULT_JSON")
    args = parser.parse_args()
    try:
        if args.verify_embedded:
            failures = verify_embedded(args.verify_embedded)
            if failures is None:
                print(json.dumps({
                    "status": "not_a_rederivable_record",
                    "file": args.verify_embedded,
                    "detail": "observational summary; raw per-request inputs are not included",
                }))
                return 2
            if failures:
                print(json.dumps({"status": "mismatch", "failures": failures}, indent=2))
                return 1
            print(json.dumps({"status": "verified", "file": args.verify_embedded}))
            return 0
        if not args.requests or not args.window:
            parser.error("provide requests.jsonl and window.json, or use --verify-embedded")
        print(json.dumps(aggregate(args.requests, args.window), indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"derivation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
