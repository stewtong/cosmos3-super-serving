<!-- register: public technical repository | reader: GPU inference operators | consumed: GitHub desktop and terminal -->

# Serve Cosmos3-Super on one eight-GPU node

This repository launches the NVIDIA `nvidia/Cosmos3-Super` text-to-video Generator path through vLLM-Omni on one eight-GPU B200 or H200 node. One loopback endpoint routes requests across the selected serving topology with one active generation per replica, bounded queueing, and health-aware admission.

The included benchmark evidence supports three operating profiles:

| Profile | Eight-GPU topology | B200 mean latency | B200 node throughput | H200 mean latency | H200 node throughput | Selection basis |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `latency` | 1 replica x 8 GPUs, hybrid | 68.5 s | 413.6 video-s/node-hour | 123.3 s | 229.9 video-s/node-hour | Lowest measured request latency |
| `balanced` | 4 replicas x 2 GPUs, TP-2 | 212.4 s | 529.0 video-s/node-hour | 416.5 s | 271.4 video-s/node-hour | Intermediate measured latency and node throughput |
| `throughput` | 8 replicas x 1 GPU, TP-1 | 378.1 s | 589.4 video-s/node-hour | 779.0 s | 289.1 video-s/node-hour | Highest node throughput among the four measured topologies for the pinned workload |

The measurements compare complete serving topologies. Replica count, GPUs per replica, and parallel configuration change together. They do not isolate replica count or one parallel method as the cause.

## Launch a profile

Requirements:

- one Linux node with exactly eight NVIDIA B200 or H200 GPUs;
- Docker with NVIDIA Container Toolkit support;
- Python 3.9 or newer on the host;
- about 124 GB of model weights in the Hugging Face cache, plus about 17 GB when guardrails are enabled.

Launch the throughput profile on B200:

```bash
bin/cosmos3-super serve --platform b200 --profile throughput
```

Use `--platform h200` for H200. The launcher verifies the GPU count and model, starts each replica sequentially, waits for application readiness, starts the router, and prints the endpoint only after every backend is healthy. The tested image digest and model revision come from [`config/profiles.json`](config/profiles.json).

Inspect any profile without a GPU or Docker:

```bash
bin/cosmos3-super serve --platform b200 --profile latency --dry-run
bin/cosmos3-super serve --platform b200 --profile balanced --dry-run
bin/cosmos3-super serve --platform b200 --profile throughput --dry-run
```

The measured 2 x 4 TP-4 topology remains available as an explicit override:

```bash
bin/cosmos3-super serve --platform b200 --topology 2x4
```

## Send requests through one endpoint

Every profile exposes:

```text
http://127.0.0.1:8000/v1/videos/sync
```

The router preserves the synchronous multipart request and MP4 response contract. It assigns work only to healthy, idle replicas. One request may run on each replica; additional admitted work waits in a bounded node queue. With the default throughput profile, requests one through eight run, the ninth waits, and the seventeenth returns HTTP 429 while all earlier requests remain active or queued. Queue expiry returns HTTP 504, and loss of all healthy replicas returns HTTP 503. A request that fails after backend dispatch is not replayed automatically.

The router binds to loopback. Public ingress, TLS, authentication, tenant isolation, quotas, and distributed coordination belong outside this repository.

## Inspect and stop the deployment

```bash
bin/cosmos3-super status
bin/cosmos3-super stop --dry-run
bin/cosmos3-super stop
```

`status` reads router counters, queue depth, replica health, active requests, container state, the model revision, and the image digest. `stop` prints its exact target set, then signals only the recorded router process and removes containers carrying the current run's exact ownership label.

Detailed operation, failure, queue, guardrail, and lifecycle behavior is in [`SERVING.md`](SERVING.md).

## The profiles trace to 408 validated attempts

The primary study contains 240 B200 attempts across ten cells and 168 H200 attempts across seven cells. All 408 attempts passed the technical MP4 gate. The four concurrency-one topology rows returned 24 valid clips out of 24 on each platform.

At the pinned workload:

- B200 node throughput increased from 413.6 to 589.4 video-seconds per node-hour between the 1 x 8 hybrid and 8 x 1 TP-1 topologies, a 42.50% gain. Mean request latency increased from 68.5 to 378.1 seconds, a 5.52x ratio.
- H200 node throughput increased from 229.9 to 289.1 video-seconds per node-hour, a 25.75% gain. Mean request latency increased from 123.3 to 779.0 seconds, a 6.32x ratio.
- Concurrency two changed node throughput by 0.41% to 3.24% across the four B200 topologies while increasing mean latency by 32.92% to 48.77%. The benchmark-backed admission setting is one active request per replica.

[`BENCHMARKS.md`](BENCHMARKS.md) contains all 17 primary cells, concurrency comparisons, delayed repeats, and the earlier 147-attempt B200 corroboration record. [`reproduce/METHOD.md`](reproduce/METHOD.md) defines the controls, validity gate, timing boundaries, formulas, and comparison limits.

## Serving topology combines replicas and on-GPU parallelism

A serving topology is the replica count, GPUs assigned to each replica, and parallel configuration within each replica. A replica is one independently launched vLLM-Omni container with its own endpoint and disjoint GPU group. These replicas are separate server processes, not vLLM data parallelism.

| Method | Meaning in this repository |
| --- | --- |
| Tensor parallelism | Shards supported diffusion-transformer weights and linear computation across GPUs. The text encoder remains replicated in these layouts. |
| Classifier-free-guidance parallelism | Runs the positive and negative guidance branches on separate GPU groups. |
| Ulysses sequence parallelism | Divides the video-token sequence and redistributes attention tensors through all-to-all communication. |
| HSDP | Shards model weights across configured ranks and gathers them as needed for forward execution. |

The 1 x 8 hybrid topology uses CFG parallel size 2, Ulysses degree 4, HSDP shard size 8, and Ring degree 1 across the same eight GPUs. These settings overlap; they do not describe 64 independent ranks.

## Reproduce the records or measure the routed service

No-GPU verification:

```bash
python3 -m unittest discover -s tests -v
python3 reproduce/benchmark.py --fixtures --output /tmp/cosmos3-fixture --overwrite
python3 reproduce/derive-results.py --verify-embedded results/b200-topology.json
python3 reproduce/derive-results.py --verify-embedded results/b200-single-node-20260831.json
python3 reproduce/derive-results.py --verify-embedded results/h200-single-node-20260831.json
python3 reproduce/render-benchmarks.py --check
(cd results && shasum -a 256 -c SHA256SUMS)
```

The v1 harness reproduces the published August 31, 2026 protocol: pinned prompt hashes, synchronized rounds, one warmup per replica, response timing through MP4 persistence, and technical validation after the production window closes.

The v2 harness measures a named profile through the stable router endpoint with a work-conserving closed loop. V2 results use a separate comparison basis and new output directory. They do not alter or extend the v1 records.

[`reproduce/REPRODUCE.md`](reproduce/REPRODUCE.md) gives the complete 17-cell v1 matrix, prompt-hash preflight, one-cell commands, v2 routed commands, direct-backend controls, output files, and teardown boundaries.

## Scope and rights

The evidence covers the BF16 text-to-video Generator path at 1280 x 720, 189 frames, 24 fps, 35 denoising steps, guidance 6.0, flow shift 10.0, maximum sequence length 4096, guardrails disabled, seeds 17/23/41, and the pinned public container and model revision. It does not establish transfer to another model, engine, image, request shape, node size, acceptance gate, or future runtime.

Technical validity checks file integrity, complete decode, shape, duration, spatial detail, and frame-to-frame change. It does not measure prompt adherence, visual quality, temporal consistency, physical plausibility, realism, human acceptance, or downstream training utility.

Repository-authored code, prose, and sanitized records are licensed under the [Apache License 2.0](LICENSE). [`PROVENANCE.md`](PROVENANCE.md) records the third-party terms that remain separate. Model weights, prompt text, generated videos, container layers, credentials, and infrastructure identifiers are excluded from the repository.
