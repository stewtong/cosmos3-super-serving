<!-- register: public reproduction guide | reader: benchmark operators and reviewers | consumed: terminal alongside an eight-GPU node -->

# Reproduce the Cosmos3-Super serving study

V1 reproduces the published August 31, 2026 evidence. V2 measures a named profile through the node-local router. Results from one contract cannot be relabeled or combined with the other.

## No-GPU checks verify the public evidence

Run from the repository root:

```bash
python3 -m unittest discover -s tests -v
python3 reproduce/benchmark.py --fixtures --output /tmp/cosmos3-fixture --overwrite
python3 reproduce/derive-results.py --verify-embedded results/b200-topology.json
python3 reproduce/derive-results.py --verify-embedded results/b200-single-node-20260831.json
python3 reproduce/derive-results.py --verify-embedded results/h200-single-node-20260831.json
python3 reproduce/render-benchmarks.py --check
(cd results && shasum -a 256 -c SHA256SUMS)
```

The three embedded records return `verified`. The four supplemental environment and serving-envelope files return `not_a_rederivable_record` with exit code 2 because they do not contain per-attempt inputs.

## Prompt preflight verifies the pinned workload

Locate these files in the pinned `nvidia/Cosmos3-Super` snapshot:

```text
assets/example_t2v_prompt.json
assets/negative_prompt.json
```

Check their normalized hashes without printing prompt text:

```bash
python3 reproduce/benchmark.py --check-prompts \
  --prompt <snapshot>/assets/example_t2v_prompt.json \
  --negative-prompt <snapshot>/assets/negative_prompt.json
```

Expected SHA-256 values after UTF-8 reading and leading/trailing whitespace removal:

```text
positive  61c9c4b46b6787d967cc509a2bf323766e70bf5ecf40e09a739362beac135677
negative  007a1bdfe1ec3edf3b9a71789ca1999a47ad565560f269a3d78bf9a8dfef9cfd
```

The v1 runner refuses a mismatch. `--new-workload` permits a separate non-comparable run and records that identity in `window.json`.

## One v1 cell uses direct backend endpoints

Launch the complete topology. The node-local router also starts, but v1 sends requests directly to backend ports so its timing and dispatch contract match the published runner.

```bash
bin/cosmos3-super serve --platform b200 --topology 8x1
```

Run 24 production attempts with one warmup per replica:

```bash
python3 reproduce/benchmark.py \
  --topology 8x1 \
  --ports 8100,8101,8102,8103,8104,8105,8106,8107 \
  --prompt <snapshot>/assets/example_t2v_prompt.json \
  --negative-prompt <snapshot>/assets/negative_prompt.json \
  --attempts 24 \
  --concurrency 1 \
  --warmups-per-replica 1 \
  --output ./runs/v1-b200-T4_8x1
```

Inspect and stop the exact deployment:

```bash
bin/cosmos3-super status
bin/cosmos3-super stop --dry-run
bin/cosmos3-super stop
```

Each cell writes:

```text
<output>/window.json
<output>/requests.jsonl
<output>/warmups.jsonl
<output>/clips/<attempt-id>.mp4
```

The runner refuses a non-empty output directory unless `--overwrite` is explicit. Every attempt remains in `requests.jsonl` when HTTP, transport, persistence, or validation fails. A validation failure returns nonzero after the full record set and original production window have been written.

## V1 covers both platforms and all measured topologies

| Platform | Cell | Topology | Requests in flight per replica | Production attempts | Backend ports |
| --- | --- | --- | ---: | ---: | --- |
| B200 | `T1_1x8` | 1 x 8 hybrid | 1 | 24 | 8100 |
| B200 | `T2_2x4` | 2 x 4 TP-4 | 1 | 24 | 8100-8101 |
| B200 | `T3_4x2` | 4 x 2 TP-2 | 1 | 24 | 8100-8103 |
| B200 | `T4_8x1` | 8 x 1 TP-1 | 1 | 24 | 8100-8107 |
| B200 | `T1C2` | 1 x 8 hybrid | 2 | 24 | 8100 |
| B200 | `T2C2` | 2 x 4 TP-4 | 2 | 24 | 8100-8101 |
| B200 | `T3C2` | 4 x 2 TP-2 | 2 | 24 | 8100-8103 |
| B200 | `T4C2` | 8 x 1 TP-1 | 2 | 24 | 8100-8107 |
| B200 | `T1R` | 1 x 8 hybrid delayed repeat | 1 | 24 | 8100 |
| B200 | `T1C2R` | 1 x 8 hybrid delayed repeat | 2 | 24 | 8100 |
| H200 | `H1_1x8` | 1 x 8 hybrid | 1 | 24 | 8100 |
| H200 | `H2_2x4` | 2 x 4 TP-4 | 1 | 24 | 8100-8101 |
| H200 | `H3_4x2` | 4 x 2 TP-2 | 1 | 24 | 8100-8103 |
| H200 | `H4_8x1` | 8 x 1 TP-1 | 1 | 24 | 8100-8107 |
| H200 | `H2C2` | 2 x 4 TP-4 | 2 | 24 | 8100-8101 |
| H200 | `H3C2` | 4 x 2 TP-2 | 2 | 24 | 8100-8103 |
| H200 | `H1R` | 1 x 8 hybrid delayed repeat | 1 | 24 | 8100 |

Every cell uses one warmup per replica outside the production window. The original B200 record combined two measurement sessions on the same node. A reproduction should preserve that fact in its environment and run notes rather than imply one uninterrupted collection.

Preview the exact commands and output paths for a platform:

```bash
python3 reproduce/run-v1-matrix.py \
  --platform b200 \
  --prompt <snapshot>/assets/example_t2v_prompt.json \
  --negative-prompt <snapshot>/assets/negative_prompt.json \
  --output-root ./runs/v1-b200-reproduction
```

Add `--execute` to run the selected cells sequentially. Use `--cells T1_1x8,T4_8x1` for a bounded subset. The driver starts a fresh owned topology for each cell, runs the v1 harness, and performs exact-label teardown before continuing.

Repeat cells measure drift after other work has elapsed. Record the elapsed time from the original cell to its repeat. A subset containing only an original and repeat needs an operator-chosen delay; the cell name itself does not create one.

## V1 preserves synchronized rounds and post-window validation

Within a production round, requests start concurrently across every replica. Concurrency one dispatches one request per replica; concurrency two dispatches up to two. The next round waits for every request in the current round. This preserves replica skew in the node makespan.

The request timer stops after the response has been fully read and persisted. `window_end_utc` is recorded before MP4 validation starts. Validation results and timestamps are merged into the attempt records afterward. Artificially slower validation therefore does not change request latency or production-window makespan.

Re-derive a new cell:

```bash
python3 reproduce/derive-results.py \
  ./runs/v1-b200-T4_8x1/requests.jsonl \
  ./runs/v1-b200-T4_8x1/window.json
```

## V2 measures the stable routed endpoint

Launch a named profile:

```bash
bin/cosmos3-super serve --platform b200 --profile throughput
```

Measure the router with one closed-loop worker per measured replica:

```bash
python3 reproduce/benchmark-v2.py \
  --profile throughput \
  --mode routed \
  --endpoint http://127.0.0.1:8000/v1/videos/sync \
  --prompt <snapshot>/assets/example_t2v_prompt.json \
  --negative-prompt <snapshot>/assets/negative_prompt.json \
  --attempts 24 \
  --output ./runs/v2-b200-throughput-<date>
```

V2 records `cosmos3_super_serving_v2`, the profile and topology, router policy, worker capacity, queue settings, healthy capacity at the window boundaries, request latency, validity, and node makespan. Its work-conserving closed loop submits a replacement when one request completes and does not intentionally fill the queue.

Measure the matching direct-backend control against the same live deployment:

```bash
python3 reproduce/benchmark-v2.py \
  --profile throughput \
  --mode direct \
  --direct-ports 8100,8101,8102,8103,8104,8105,8106,8107 \
  --prompt <snapshot>/assets/example_t2v_prompt.json \
  --negative-prompt <snapshot>/assets/negative_prompt.json \
  --attempts 24 \
  --output ./runs/v2-b200-throughput-direct-<date>
```

Keep routed and direct results in separate dated directories. Report router overhead only from a matched pair with the same live deployment, workload, attempt count, and load schedule.

A saturation control may submit above measured capacity to characterize HTTP 429 and 504 behavior. Label it as a queue control rather than profile throughput evidence.

After an operator deliberately removes one exact backend from an eight-replica throughput deployment, the v2 client can require the resulting degraded health state before sending a control request:

```bash
python3 reproduce/benchmark-v2.py \
  --profile throughput \
  --mode routed \
  --expected-healthy-replicas 7 \
  --expected-unavailable-replicas 1 \
  --endpoint http://127.0.0.1:8000/v1/videos/sync \
  --prompt <snapshot>/assets/example_t2v_prompt.json \
  --negative-prompt <snapshot>/assets/negative_prompt.json \
  --attempts 1 \
  --warmups-per-worker 0 \
  --output ./runs/v2-h200-throughput-degraded-<date>
```

The two expected replica counts must be nonnegative and sum to the profile capacity. These options validate an operator-created health state; they do not stop a backend. Label this run as a health-routing control rather than throughput evidence.

## Included records remain immutable evidence

Verify the published result files from the manifest directory:

```bash
(cd results && shasum -a 256 -c SHA256SUMS)
```

New v1 reproductions and v2 measurements belong in new dated files. Do not rewrite historical records, append v2 cells to v1 JSON, or reuse a v1 `comparison_basis` for routed results.
