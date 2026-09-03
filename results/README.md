<!-- register: public evidence index | reader: benchmark reviewers | consumed: file-by-file verification on GitHub -->

# Result records and evidence levels

The directory contains three aggregate-rederivable records, four supplemental summaries, and one live operability record. Historical JSON files remain unchanged so their checksums and original scope statements stay auditable.

## Primary records define the 408-attempt study

| File | Platform | Cells | Attempts | Role |
| --- | --- | ---: | ---: | --- |
| [`b200-single-node-20260831.json`](b200-single-node-20260831.json) | B200 | 10 | 240 | Primary topology, concurrency, and repeat record |
| [`h200-single-node-20260831.json`](h200-single-node-20260831.json) | H200 | 7 | 168 | Primary matched topology, concurrency, and repeat record |

Each cell embeds sanitized per-attempt records, an exact production window, derived aggregates, and checked comparisons. All 408 attempts passed the technical MP4 gate.

## Earlier B200 evidence corroborates the ordering

[`b200-topology.json`](b200-topology.json) contains 147 attempts across seven cells. It reproduced the four-topology ordering before the later single-node consolidation. It remains corroborating evidence and is excluded from the 408-attempt primary count.

## Supplemental summaries have narrower verification

| File | Content | Verification boundary |
| --- | --- | --- |
| [`b200-serving-envelope.json`](b200-serving-envelope.json) | startup, hybrid versus TP-8, guardrail, concurrency, determinism, and NVIDIA-grid observations | Aggregate summary; no embedded per-request inputs |
| [`h200-serving-envelope.json`](h200-serving-envelope.json) | startup, hybrid versus TP-8, guardrail, concurrency, and determinism observations | Aggregate summary; no embedded per-request inputs |
| [`b200-environment.json`](b200-environment.json) | platform and software inventory from the earlier evidence assembly | Environment summary |
| [`h200-environment.json`](h200-environment.json) | platform and software inventory from the earlier evidence assembly | Environment summary |

## Live validation covers the serving path

[`runtime-validation-20260903.json`](runtime-validation-20260903.json) records a live H200 operability pass for the three named profiles, bounded admission, unhealthy-replica removal, and exact teardown. It contains sanitized verdicts and output hashes without smoke-test performance figures. It is excluded from the 408-attempt primary benchmark count and does not establish live B200 launcher coverage.

The environment summaries were written before the final August 31 topology cells. Their embedded exclusion arrays preserve that earlier state and are superseded by the current scope in [`../reproduce/METHOD.md`](../reproduce/METHOD.md). The files stay byte-stable as historical evidence.

## Verification distinguishes rederivable and observational records

```bash
python3 reproduce/derive-results.py --verify-embedded results/b200-topology.json
python3 reproduce/derive-results.py --verify-embedded results/b200-single-node-20260831.json
python3 reproduce/derive-results.py --verify-embedded results/h200-single-node-20260831.json
```

These commands recompute every cell aggregate and comparison and return `verified` only on an exact match.

Passing any supplemental file to the same command returns `not_a_rederivable_record` with exit code 2. This prevents an aggregate-only summary from being mistaken for independently recomputed evidence.

Verify file integrity from this directory:

```bash
shasum -a 256 -c SHA256SUMS
```

New reproductions and v2 router measurements belong in new dated files. They should carry their method version and comparison basis rather than modifying these records.
