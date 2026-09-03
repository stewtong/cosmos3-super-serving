#!/usr/bin/env python3
"""Measure a deployed Cosmos3-Super profile through the v2 serving contract."""

import argparse
import concurrent.futures
import importlib.util
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = load_module("benchmark_v1", ROOT / "reproduce" / "benchmark.py")


def router_status(endpoint):
    base = endpoint.split("/v1/videos/sync", 1)[0]
    try:
        with urllib.request.urlopen(base + "/status", timeout=3) as response:
            value = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return {
        "profile": value.get("profile"),
        "topology": value.get("topology"),
        "policy": value.get("policy"),
        "active_requests_per_replica": value.get("active_requests_per_replica"),
        "queue_limit": value.get("queue_limit"),
        "queue_timeout_seconds": value.get("queue_timeout_seconds"),
        "guardrails": value.get("guardrails"),
        "healthy_replicas": value.get("healthy_replicas"),
        "unavailable_replicas": value.get("unavailable_replicas"),
        "counters": value.get("counters"),
    }


def closed_loop(endpoints, base_fields, attempts, timeout_s, clips_dir, kind):
    workers = len(endpoints)

    def run_worker(worker):
        rows = []
        for index in range(worker, attempts, workers):
            fields = dict(base_fields)
            fields["seed"] = str(V1.SEEDS[index % len(V1.SEEDS)])
            rows.append(V1.measure_attempt(
                endpoints[worker], fields, timeout_s, clips_dir,
                f"{kind}-w{worker}-a{index:03d}", f"w{worker}", kind,
            ))
        return rows

    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run_worker, worker) for worker in range(workers)]
        for future in concurrent.futures.as_completed(futures):
            rows.extend(future.result())
    return sorted(rows, key=lambda row: (row["started_utc"], row["attempt_id"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=("latency", "balanced", "throughput"))
    parser.add_argument("--mode", choices=("routed", "direct"), default="routed")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/v1/videos/sync")
    parser.add_argument("--direct-ports", default="")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--negative-prompt", default="")
    parser.add_argument("--new-workload", action="store_true")
    parser.add_argument("--attempts", type=int, default=24)
    parser.add_argument("--warmups-per-worker", type=int, default=1)
    parser.add_argument("--expected-healthy-replicas", type=int)
    parser.add_argument("--expected-unavailable-replicas", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=5400)
    parser.add_argument("--output", default="./bench-v2-out")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.attempts < 1 or args.warmups_per_worker < 0:
        parser.error("attempts must be positive and warmups must be nonnegative")

    with open(ROOT / "config" / "profiles.json", encoding="utf-8") as handle:
        config = json.load(handle)
    topology_name = config["profiles"][args.profile]["topology"]
    capacity = config["topologies"][topology_name]["replicas"]
    expected_healthy = (
        capacity if args.expected_healthy_replicas is None
        else args.expected_healthy_replicas
    )
    if (
        expected_healthy < 0
        or args.expected_unavailable_replicas < 0
        or expected_healthy + args.expected_unavailable_replicas != capacity
    ):
        parser.error(
            "expected healthy and unavailable replicas must be nonnegative "
            "and sum to the profile capacity"
        )
    if args.mode == "routed":
        endpoints = [args.endpoint] * capacity
    else:
        ports = [int(value) for value in args.direct_ports.split(",") if value.strip()]
        if len(ports) != capacity:
            parser.error(f"direct mode for {args.profile} needs {capacity} backend ports")
        endpoints = [f"http://127.0.0.1:{port}/v1/videos/sync" for port in ports]

    if args.dry_run:
        print(json.dumps({
            "protocol_version": "v2",
            "comparison_basis": "cosmos3_super_serving_v2",
            "profile": args.profile,
            "topology": topology_name,
            "mode": args.mode,
            "worker_capacity": capacity,
            "expected_healthy_replicas": expected_healthy,
            "expected_unavailable_replicas": args.expected_unavailable_replicas,
            "load_schedule": "work-conserving closed loop",
            "validation_boundary": "after the production window closes",
        }, indent=2))
        return 0

    try:
        prompt, negative = V1.read_prompt(args.prompt, args.negative_prompt)
        hashes, comparable = V1.check_prompt_hashes(
            prompt, negative, allow_new_workload=args.new_workload
        )
        fields = dict(V1.DEFAULT_SHAPE)
        fields.update({
            "prompt": prompt,
            "negative_prompt": negative,
            "extra_params": json.dumps({
                "use_resolution_template": False,
                "use_duration_template": False,
                "guardrails": False,
            }),
            "_prompt_sha256": hashes["prompt"],
            "_negative_prompt_sha256": hashes["negative_prompt"],
            "_guardrail": "disabled",
        })
        clips_dir = os.path.join(args.output, "clips")
        if args.mode == "routed":
            deployed = router_status(args.endpoint)
            expected = {
                "profile": args.profile,
                "topology": topology_name,
                "active_requests_per_replica": 1,
                "healthy_replicas": expected_healthy,
                "unavailable_replicas": args.expected_unavailable_replicas,
                "guardrails": False,
            }
            mismatched = {
                key: {"expected": value, "observed": None if deployed is None else deployed.get(key)}
                for key, value in expected.items()
                if deployed is None or deployed.get(key) != value
            }
            if mismatched:
                raise ValueError(f"router deployment does not match requested v2 profile: {mismatched}")
        V1.prepare_output(args.output, overwrite=args.overwrite)
        warmup_count = capacity * args.warmups_per_worker
        warmups = closed_loop(
            endpoints, fields, warmup_count, args.timeout, clips_dir, "warmup"
        ) if warmup_count else []
        V1.validate_records(warmups, clips_dir)
        if any(not row["technical_valid"] for row in warmups):
            V1.write_output([], warmups, {
                "protocol_version": "v2",
                "comparison_basis": "cosmos3_super_serving_v2",
                "error": "warmup failed",
            }, args.output)
            print("a warmup failed validation; production window did not start", file=sys.stderr)
            return 1

        status_before = router_status(args.endpoint) if args.mode == "routed" else None
        if args.mode == "routed" and (
            status_before is None
            or status_before.get("healthy_replicas") != expected_healthy
            or status_before.get("unavailable_replicas")
            != args.expected_unavailable_replicas
        ):
            raise ValueError("router lost expected health state before the production window")
        window_start_utc = V1.utc_now()
        started = time.monotonic()
        records = closed_loop(
            endpoints, fields, args.attempts, args.timeout, clips_dir, "production"
        )
        window_seconds = time.monotonic() - started
        window_end_utc = V1.utc_now()
        validation_run_id = V1.validate_records(records, clips_dir)
        status_after = router_status(args.endpoint) if args.mode == "routed" else None
        window = {
            "protocol_version": "v2",
            "comparison_basis": "cosmos3_super_serving_v2",
            "published_v1_workload_match": comparable,
            "profile": args.profile,
            "topology": topology_name,
            "mode": args.mode,
            "load_schedule": "work_conserving_closed_loop",
            "worker_capacity": capacity,
            "expected_healthy_replicas": expected_healthy,
            "expected_unavailable_replicas": args.expected_unavailable_replicas,
            "window_start_utc": window_start_utc,
            "window_end_utc": window_end_utc,
            "window_seconds": round(window_seconds, 6),
            "boundary": "client dispatch through complete response persistence; validation excluded",
            "validation_run_id": validation_run_id,
            "validation_completed_utc": V1.utc_now(),
            "node_gpu_count": 8,
            "prompt_hashes": hashes,
            "router_status_start": status_before,
            "router_status_end": status_after,
        }
        V1.write_output(records, warmups, window, args.output)
        valid = sum(row["technical_valid"] for row in records)
        print(f"{valid}/{len(records)} technically valid; window {window_seconds:.3f} seconds")
        status_complete = args.mode == "direct" or status_after is not None
        return 0 if valid == len(records) and status_complete else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"v2 benchmark failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
