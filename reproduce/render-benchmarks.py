#!/usr/bin/env python3
"""Render or verify BENCHMARKS.md from the embedded result records."""

import argparse
import importlib.util
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "BENCHMARKS.md"
PRIMARY = (
    ("B200", ROOT / "results" / "b200-single-node-20260831.json"),
    ("H200", ROOT / "results" / "h200-single-node-20260831.json"),
)
CORROBORATING = ROOT / "results" / "b200-topology.json"
CELL_ORDER = {
    "b200_single_node_20260831": (
        "T1_1x8", "T2_2x4", "T3_4x2", "T4_8x1",
        "T1C2", "T2C2", "T3C2", "T4C2", "T1R", "T1C2R",
    ),
    "h200_single_node_20260831": (
        "H1_1x8", "H2_2x4", "H3_4x2", "H4_8x1",
        "H2C2", "H3C2", "H1R",
    ),
    "b200_topology": (
        "T1_1x8", "T2_2x4", "T3_4x2", "T4_8x1",
        "T1C2", "T4C2", "T1DRIFT",
    ),
}


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def verify_record(path):
    module_path = ROOT / "reproduce" / "derive-results.py"
    spec = importlib.util.spec_from_file_location("derive_results_for_render", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    failures = module.verify_embedded(str(path))
    if failures:
        raise ValueError(f"embedded aggregate mismatch in {path}: {failures}")


def delta(new, baseline):
    return round((new / baseline - 1) * 100, 2)


def cell_concurrency(name):
    return 2 if "C2" in name else 1


def role(name):
    if "DRIFT" in name:
        return "drift"
    if name.endswith("R"):
        return "repeat"
    if "C2" in name:
        return "concurrency"
    return "primary"


def compact_layout(layout):
    return layout.replace("services", "replicas").replace("service", "replica")


def table(document):
    lines = [
        "| Cell | Role | Serving topology | Requests per replica | Valid / attempted | Mean latency | Median latency | P95 latency | Video-seconds / node-hour |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    order = CELL_ORDER[document["comparison_basis"]]
    for name in order:
        cell = document["cells"][name]
        derived = cell["derived"]
        lines.append(
            f"| `{name}` | {role(name)} | {compact_layout(cell['layout'])} | "
            f"{cell_concurrency(name)} | {derived['valid_attempts']} / {derived['attempts']} | "
            f"{derived['mean_client_wall_s']:.3f} s | {derived['median_client_wall_s']:.3f} s | "
            f"{derived['p95_client_wall_s']:.3f} s | {derived['video_seconds_per_node_hour']:.1f} |"
        )
    return lines


def primary_comparison(b200, h200):
    pairs = (
        ("1 x 8 hybrid", "T1_1x8", "H1_1x8", "latency"),
        ("2 x 4 TP-4", "T2_2x4", "H2_2x4", "explicit override"),
        ("4 x 2 TP-2", "T3_4x2", "H3_4x2", "balanced"),
        ("8 x 1 TP-1", "T4_8x1", "H4_8x1", "throughput"),
    )
    bbase = b200["cells"]["T1_1x8"]["derived"]
    hbase = h200["cells"]["H1_1x8"]["derived"]
    lines = [
        "| Topology | Named profile | B200 mean latency | B200 node throughput | B200 throughput gain | H200 mean latency | H200 node throughput | H200 throughput gain |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for topology, bcell, hcell, profile in pairs:
        bd = b200["cells"][bcell]["derived"]
        hd = h200["cells"][hcell]["derived"]
        bgain = delta(bd["video_seconds_per_node_hour"], bbase["video_seconds_per_node_hour"])
        hgain = delta(hd["video_seconds_per_node_hour"], hbase["video_seconds_per_node_hour"])
        lines.append(
            f"| {topology} | `{profile}` | {bd['mean_client_wall_s']:.1f} s | "
            f"{bd['video_seconds_per_node_hour']:.1f} | {bgain:+.2f}% | "
            f"{hd['mean_client_wall_s']:.1f} s | {hd['video_seconds_per_node_hour']:.1f} | {hgain:+.2f}% |"
        )
    return lines


def concurrency_table(b200, h200):
    pairs = (
        ("B200", b200, "T1_1x8", "T1C2"),
        ("B200", b200, "T2_2x4", "T2C2"),
        ("B200", b200, "T3_4x2", "T3C2"),
        ("B200", b200, "T4_8x1", "T4C2"),
        ("H200", h200, "H2_2x4", "H2C2"),
        ("H200", h200, "H3_4x2", "H3C2"),
    )
    lines = [
        "| Platform | Topology cell | Concurrency-two cell | Node-throughput change | Mean-latency change |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for platform, document, base_name, concurrent_name in pairs:
        base = document["cells"][base_name]["derived"]
        concurrent = document["cells"][concurrent_name]["derived"]
        lines.append(
            f"| {platform} | `{base_name}` | `{concurrent_name}` | "
            f"{delta(concurrent['video_seconds_per_node_hour'], base['video_seconds_per_node_hour']):+.2f}% | "
            f"{delta(concurrent['mean_client_wall_s'], base['mean_client_wall_s']):+.2f}% |"
        )
    return lines


def repeat_table(b200, h200):
    pairs = (
        ("B200", b200, "T1_1x8", "T1R"),
        ("B200", b200, "T1C2", "T1C2R"),
        ("H200", h200, "H1_1x8", "H1R"),
    )
    lines = [
        "| Platform | Original | Delayed repeat | Node-throughput change | Mean-latency change |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for platform, document, base_name, repeat_name in pairs:
        base = document["cells"][base_name]["derived"]
        repeat = document["cells"][repeat_name]["derived"]
        lines.append(
            f"| {platform} | `{base_name}` | `{repeat_name}` | "
            f"{delta(repeat['video_seconds_per_node_hour'], base['video_seconds_per_node_hour']):+.2f}% | "
            f"{delta(repeat['mean_client_wall_s'], base['mean_client_wall_s']):+.2f}% |"
        )
    return lines


def render():
    for _platform, path in PRIMARY:
        verify_record(path)
    verify_record(CORROBORATING)
    b200 = read_json(PRIMARY[0][1])
    h200 = read_json(PRIMARY[1][1])
    earlier = read_json(CORROBORATING)
    attempts = sum(
        cell["derived"]["attempts"]
        for document in (b200, h200)
        for cell in document["cells"].values()
    )
    valid = sum(
        cell["derived"]["valid_attempts"]
        for document in (b200, h200)
        for cell in document["cells"].values()
    )
    lines = [
        "<!-- register: public technical repository | reader: GPU inference operators | consumed: GitHub desktop and terminal -->",
        "<!-- generated by reproduce/render-benchmarks.py from the three embedded result records -->",
        "",
        "# Cosmos3-Super serving benchmarks",
        "",
        "The primary study contains 17 cells and 408 attempts: 240 attempts across ten B200 cells and 168 attempts across seven H200 cells. All 408 attempts passed the technical MP4 gate. Technical validity covers file integrity, complete decode, shape, duration, spatial detail, and frame-to-frame change. It does not score prompt adherence, visual quality, temporal consistency, physical plausibility, realism, human acceptance, or training utility.",
        "",
        "The four primary rows compare complete serving topologies. Replica count, GPUs per replica, and parallel configuration change together. The measurements do not isolate one of those factors as the cause.",
        "",
        "![Four eight-GPU serving topologies, from one hybrid replica through eight single-GPU replicas](docs/assets/cosmos3-super-gpu-topologies.svg)",
        "",
        "## The profiles select different operating points",
        "",
        *primary_comparison(b200, h200),
        "",
        "Eight single-GPU replicas produced the highest node throughput among the four measured topologies for the pinned workload on both platforms. One eight-GPU hybrid replica produced the lowest request latency. The `balanced` profile selects the measured 4 x 2 TP-2 point between them. These are workload-bounded profile descriptions, not universal optimality claims.",
        "",
        "![Latency and node-throughput tradeoffs for the four B200 and H200 topologies](docs/assets/cosmos3-super-latency-throughput-tradeoffs.svg)",
        "",
        "## B200 latency and node throughput",
        "",
        "Source: [`results/b200-single-node-20260831.json`](results/b200-single-node-20260831.json). The B200 record combines two measurement sessions on the same node under one driver and container image.",
        "",
        *table(b200),
        "",
        "## H200 latency and node throughput",
        "",
        "Source: [`results/h200-single-node-20260831.json`](results/h200-single-node-20260831.json). The matched software and workload controls are the same as the B200 record. GPU model and memory, VBIOS, host CPU, host memory, and instance preset differ.",
        "",
        *table(h200),
        "",
        "## Concurrency two added latency for small throughput changes",
        "",
        *concurrency_table(b200, h200),
        "",
        "Concurrency-two cells are bimodal because the second request at a replica waits for the first. The table uses mean latency so both the fast and queued groups contribute to the comparison.",
        "",
        "## Delayed repeats bound within-node drift",
        "",
        *repeat_table(b200, h200),
        "",
        "## The earlier B200 record corroborates the topology ordering",
        "",
        "[`results/b200-topology.json`](results/b200-topology.json) contains 147 attempts across seven cells. It is corroborating evidence and is excluded from the 408-attempt primary census.",
        "",
        *table(earlier),
        "",
        "## Metrics and boundaries",
        "",
        "Request latency is client wall time from dispatch through receipt and persistence of the complete MP4. Post-response validation is outside the request and production-window timers. Node throughput is validator-passing video duration divided by the production-window makespan, normalized to one node-hour. Failed and rejected attempts contribute no video-seconds while their elapsed time remains in the production window. Warmup, service construction, and model loading are outside the production window.",
        "",
        f"The primary records contain {valid} technically valid attempts out of {attempts}. Run `python3 reproduce/render-benchmarks.py --check` to detect table drift and `python3 reproduce/derive-results.py --verify-embedded <record>` to rederive every aggregate.",
        "",
        "The exact control set and formulas are in [`reproduce/METHOD.md`](reproduce/METHOD.md). Commands for no-GPU verification, one-cell reproduction, the full v1 matrix, and routed v2 measurement are in [`reproduce/REPRODUCE.md`](reproduce/REPRODUCE.md).",
        "",
    ]
    if attempts != 408 or valid != 408:
        raise ValueError(f"expected 408 valid attempts, found {valid}/{attempts}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    try:
        rendered = render()
        output = pathlib.Path(args.output)
        if args.check:
            current = output.read_text(encoding="utf-8")
            if current != rendered:
                print(f"benchmark document drift: {output}", file=sys.stderr)
                return 1
            print(f"benchmark document verified: 17 cells, 408/408 technically valid attempts")
            return 0
        output.write_text(rendered, encoding="utf-8")
        print(f"wrote {output}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"benchmark rendering failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
