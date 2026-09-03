#!/usr/bin/env python3
"""Plan or execute the 17-cell Cosmos3-Super v1 reproduction matrix."""

import argparse
import json
import pathlib
import shlex
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "cosmos3-super"
BENCHMARK = ROOT / "reproduce" / "benchmark.py"
MATRIX = {
    "b200": [
        ("T1_1x8", "1x8", 1),
        ("T2_2x4", "2x4", 1),
        ("T3_4x2", "4x2", 1),
        ("T4_8x1", "8x1", 1),
        ("T1C2", "1x8", 2),
        ("T2C2", "2x4", 2),
        ("T3C2", "4x2", 2),
        ("T4C2", "8x1", 2),
        ("T1R", "1x8", 1),
        ("T1C2R", "1x8", 2),
    ],
    "h200": [
        ("H1_1x8", "1x8", 1),
        ("H2_2x4", "2x4", 1),
        ("H3_4x2", "4x2", 1),
        ("H4_8x1", "8x1", 1),
        ("H2C2", "2x4", 2),
        ("H3C2", "4x2", 2),
        ("H1R", "1x8", 1),
    ],
}


def command_text(command):
    return " ".join(shlex.quote(str(value)) for value in command)


def cell_commands(platform, cell, topology, concurrency, output_root, prompt, negative):
    replicas = int(topology.split("x", 1)[0])
    ports = ",".join(str(8100 + index) for index in range(replicas))
    output = output_root / cell
    serve = [str(CLI), "serve", "--platform", platform, "--topology", topology]
    benchmark = [
        sys.executable,
        str(BENCHMARK),
        "--topology", topology,
        "--ports", ports,
        "--prompt", prompt,
        "--negative-prompt", negative,
        "--attempts", "24",
        "--concurrency", str(concurrency),
        "--warmups-per-replica", "1",
        "--output", str(output),
    ]
    stop = [str(CLI), "stop"]
    return serve, benchmark, stop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=MATRIX)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--negative-prompt", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--cells", default="", help="comma-separated cell IDs; default is the full platform matrix")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    output_root = pathlib.Path(args.output_root)
    if output_root.exists() and not output_root.is_dir():
        print(f"output root is not a directory: {output_root}", file=sys.stderr)
        return 2
    if output_root.exists() and any(output_root.iterdir()):
        print(f"output root is not empty: {output_root}", file=sys.stderr)
        return 2

    requested = {value.strip() for value in args.cells.split(",") if value.strip()}
    available = {cell for cell, _, _ in MATRIX[args.platform]}
    unknown = requested - available
    if unknown:
        print("unknown cells: " + ", ".join(sorted(unknown)), file=sys.stderr)
        return 2
    selected = [row for row in MATRIX[args.platform] if not requested or row[0] in requested]
    plan = []
    for cell, topology, concurrency in selected:
        serve, benchmark, stop = cell_commands(
            args.platform, cell, topology, concurrency,
            output_root, args.prompt, args.negative_prompt,
        )
        plan.append({
            "cell": cell,
            "topology": topology,
            "concurrency": concurrency,
            "output": str(output_root / cell),
            "commands": [command_text(serve), command_text(benchmark), command_text(stop)],
        })
    if not args.execute:
        print(json.dumps({
            "protocol_version": "v1",
            "platform": args.platform,
            "cells": plan,
            "execution": "add --execute to run sequentially",
        }, indent=2))
        return 0

    output_root.mkdir(parents=True, exist_ok=True)
    for row in selected:
        cell, topology, concurrency = row
        serve, benchmark, stop = cell_commands(
            args.platform, cell, topology, concurrency,
            output_root, args.prompt, args.negative_prompt,
        )
        started = False
        try:
            subprocess.run(serve, check=True)
            started = True
            subprocess.run(benchmark, check=True)
        except subprocess.CalledProcessError as exc:
            print(f"cell {cell} failed with exit code {exc.returncode}", file=sys.stderr)
            return exc.returncode or 1
        finally:
            if started:
                stopped = subprocess.run(stop, check=False)
                if stopped.returncode != 0:
                    print(f"cell {cell} teardown failed", file=sys.stderr)
                    return stopped.returncode
    print(json.dumps({
        "status": "complete",
        "platform": args.platform,
        "cells": [cell for cell, _, _ in selected],
        "output_root": str(output_root),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
