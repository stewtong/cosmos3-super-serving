#!/usr/bin/env python3
"""Run validated Cosmos3-Super serving benchmark cells on loopback services."""
import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_SHAPE = {
    "size": "1280x720", "num_frames": "189", "fps": "24",
    "num_inference_steps": "35", "guidance_scale": "6.0",
    "flow_shift": "10.0", "max_sequence_length": "4096",
}
TOPOLOGY_REPLICAS = {"full": 1, "1x8": 1, "2x4": 2, "4x2": 4, "8x1": 8}
SEEDS = (17, 23, 41)


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_text(text):
    return sha256_bytes(text.encode("utf-8"))


def read_prompt(prompt_path, negative_path):
    if not prompt_path or not negative_path:
        raise SystemExit("provide local anchor and negative prompt files")
    with open(prompt_path, encoding="utf-8") as handle:
        prompt = handle.read()
    with open(negative_path, encoding="utf-8") as handle:
        negative = handle.read()
    return prompt, negative


def build_multipart(fields):
    boundary = "cosmos3bench" + hashlib.sha256(os.urandom(16)).hexdigest()[:24]
    chunks = []
    for key, value in fields.items():
        if key.startswith("_"):
            continue
        chunks.append((
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n"
            f"{value}\r\n"
        ).encode("utf-8"))
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def load_validator():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "validate-video.py")
    spec = importlib.util.spec_from_file_location("validate_video", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate


def one_attempt(url, fields, timeout_s, out_dir, attempt_id, replica, kind="production"):
    body, content_type = build_multipart(fields)
    started_utc = utc_now()
    started = time.monotonic()
    record = {
        "attempt_id": attempt_id, "kind": kind, "replica": replica,
        "started_utc": started_utc, "finished_utc": None,
        "request_shape": dict(DEFAULT_SHAPE),
        "prompt_sha256": fields["_prompt_sha256"],
        "negative_prompt_sha256": fields["_negative_prompt_sha256"],
        "seed": int(fields["seed"]), "guardrail_posture": fields["_guardrail"],
        "http_status": None, "client_wall_s": None, "server_generation_s": None,
        "output_bytes": None, "sha256": None, "video_validation": None,
        "technical_valid": False, "failure_reason": None,
    }
    try:
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Accept": "video/mp4", "Content-Type": content_type},
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = response.read()
            record["http_status"] = response.status
        record["output_bytes"] = len(payload)
        record["sha256"] = sha256_bytes(payload)
        if record["http_status"] != 200:
            record["failure_reason"] = f"http_{record['http_status']}"
        elif not payload:
            record["failure_reason"] = "empty_response"
        else:
            os.makedirs(out_dir, exist_ok=True)
            clip_path = os.path.join(out_dir, f"{attempt_id}.mp4")
            with open(clip_path, "wb") as handle:
                handle.write(payload)
            validation = load_validator()(clip_path)
            record["video_validation"] = validation
            record["technical_valid"] = bool(validation["valid"])
            if not validation["valid"]:
                checks = ",".join(error["check"] for error in validation["errors"])
                record["failure_reason"] = f"video_invalid:{checks}"
    except urllib.error.HTTPError as exc:
        record["http_status"] = exc.code
        record["failure_reason"] = f"http_{exc.code}"
    except Exception as exc:  # record transport, timeout, validation, and write failures
        record["failure_reason"] = f"{type(exc).__name__}:{exc}"
    record["client_wall_s"] = round(time.monotonic() - started, 3)
    record["finished_utc"] = utc_now()
    return record


def distribute_attempts(total, replicas):
    return [total // replicas + (1 if index < total % replicas else 0) for index in range(replicas)]


def dispatch(urls, base_fields, total_attempts, concurrency, timeout_s, out_dir, kind="production"):
    def run_replica(replica, url, count):
        rows = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = []
            for index in range(count):
                fields = dict(base_fields)
                fields["seed"] = str(SEEDS[index % len(SEEDS)])
                futures.append(executor.submit(
                    one_attempt, url, fields, timeout_s, out_dir,
                    f"{kind}-r{replica}-a{index:03d}", f"r{replica}", kind,
                ))
            for future in concurrent.futures.as_completed(futures):
                rows.append(future.result())
        return rows

    records = []
    counts = distribute_attempts(total_attempts, len(urls))
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(urls)) as executor:
        futures = [executor.submit(run_replica, replica, url, count)
                   for replica, (url, count) in enumerate(zip(urls, counts))]
        for future in concurrent.futures.as_completed(futures):
            records.extend(future.result())
    return sorted(records, key=lambda record: (record["started_utc"], record["attempt_id"]))


def write_output(records, warmups, window, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for name, rows in (("requests.jsonl", records), ("warmups.jsonl", warmups)):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    with open(os.path.join(out_dir, "window.json"), "w", encoding="utf-8") as handle:
        json.dump(window, handle, indent=2, sort_keys=True)


def fixture_records():
    records = []
    for index in range(12):
        valid = index != 11
        records.append({
            "attempt_id": f"fixture-r0-a{index:03d}", "kind": "production", "replica": "r0",
            "started_utc": f"2026-08-30T00:00:{index:02d}Z",
            "finished_utc": f"2026-08-30T00:00:{index + 1:02d}Z",
            "request_shape": dict(DEFAULT_SHAPE), "prompt_sha256": "fixture",
            "negative_prompt_sha256": "fixture", "seed": SEEDS[index % 3],
            "guardrail_posture": "disabled", "http_status": 200,
            "client_wall_s": 1.0, "server_generation_s": None,
            "output_bytes": 100 if valid else 0, "sha256": "fixture" if valid else None,
            "video_validation": {"valid": valid, "errors": [] if valid else [{"check": "blank"}]},
            "technical_valid": valid, "failure_reason": None if valid else "video_invalid:blank",
        })
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "localhost"])
    parser.add_argument("--topology", choices=TOPOLOGY_REPLICAS, default="full")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--ports", default="", help="comma-separated loopback ports")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--negative-prompt", default="")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--attempts", type=int, default=24, help="total production attempts in the cell")
    parser.add_argument("--warmups-per-replica", type=int, default=1)
    parser.add_argument("--guardrails", action="store_true")
    parser.add_argument("--timeout", type=int, default=5400)
    parser.add_argument("--output", default="./bench-out")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fixtures", action="store_true")
    args = parser.parse_args()
    if args.concurrency < 1 or args.attempts < 1 or args.warmups_per_replica < 0:
        parser.error("concurrency and attempts must be positive; warmups must be nonnegative")

    base = dict(DEFAULT_SHAPE)
    base["extra_params"] = json.dumps({
        "use_resolution_template": False, "use_duration_template": False,
        "guardrails": args.guardrails,
    })
    if args.dry_run:
        print(json.dumps({
            "endpoint": "POST /v1/videos/sync", "fields": base,
            "seed_cycle": SEEDS, "client_timeout_seconds": args.timeout,
            "server_required": "loopback service with VLLM_OMNI_VIDEO_SYNC_TIMEOUT=5400",
            "prompt_text": "read locally; only SHA256 is recorded",
        }, indent=2))
        return 0

    if args.fixtures:
        records = fixture_records()
        window = {
            "window_start_utc": "2026-08-30T00:00:00Z", "window_end_utc": "2026-08-30T00:00:12Z",
            "window_seconds": 12.0, "node_gpu_count": 8, "concurrency": 1,
            "topology": "fixture", "replicas": 1,
        }
        write_output(records, [], window, args.output)
        here = os.path.dirname(os.path.abspath(__file__))
        spec = importlib.util.spec_from_file_location("derive_results", os.path.join(here, "derive-results.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        aggregate = module.aggregate(os.path.join(args.output, "requests.jsonl"), os.path.join(args.output, "window.json"))
        if aggregate["valid_attempts"] != 11 or aggregate["failed_attempts"] != 1:
            print("fixture self-check failed", file=sys.stderr)
            return 1
        print("fixture self-check passed: 11 valid, 1 invalid; no GPU touched")
        return 0

    prompt, negative = read_prompt(args.prompt, args.negative_prompt)
    base.update({
        "prompt": prompt, "negative_prompt": negative,
        "_prompt_sha256": sha256_text(prompt), "_negative_prompt_sha256": sha256_text(negative),
        "_guardrail": "enabled" if args.guardrails else "disabled",
    })
    replicas = TOPOLOGY_REPLICAS[args.topology]
    ports = [int(value) for value in args.ports.split(",") if value.strip()]
    if ports and len(ports) != replicas:
        parser.error(f"topology {args.topology} needs {replicas} ports")
    if not ports:
        base_port = args.port if args.port is not None else (8000 if args.topology == "full" else 8100)
        ports = list(range(base_port, base_port + replicas))
    urls = [f"http://{args.host}:{port}/v1/videos/sync" for port in ports]

    warmups = dispatch(urls, base, replicas * args.warmups_per_replica, 1,
                       args.timeout, os.path.join(args.output, "clips"), "warmup") if args.warmups_per_replica else []
    if any(not row["technical_valid"] for row in warmups):
        write_output([], warmups, {"topology": args.topology, "error": "warmup failed"}, args.output)
        print("a warmup failed validation; production window did not start", file=sys.stderr)
        return 1
    window_start_utc = utc_now()
    window_start = time.monotonic()
    records = dispatch(urls, base, args.attempts, args.concurrency, args.timeout,
                       os.path.join(args.output, "clips"), "production")
    window_seconds = time.monotonic() - window_start
    window = {
        "window_start_utc": window_start_utc, "window_end_utc": utc_now(),
        "window_seconds": round(window_seconds, 6),
        "boundary": "first production dispatch to final production completion; warmups excluded",
        "node_gpu_count": 8, "concurrency": args.concurrency,
        "replicas": replicas, "topology": args.topology,
        "replica_ports": ports,
    }
    write_output(records, warmups, window, args.output)
    valid = sum(row["technical_valid"] for row in records)
    print(f"{valid}/{len(records)} technically valid; window {window_seconds:.3f} seconds")
    return 0 if valid == len(records) else 1


if __name__ == "__main__":
    sys.exit(main())
