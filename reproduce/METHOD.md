# Methodology

The included benchmark measures client wall time, validates each returned MP4,
and derives topology throughput from run-level windows. The B200 topology result
can be rederived from its embedded inputs. The H200 and B200 serving envelopes
are supplemental observations whose raw per-request inputs are not included.

## Workload

Fixed across every cell:

| Field | Value |
| --- | --- |
| Model | `nvidia/Cosmos3-Super` snapshot `e0262be9d8f7586bc24c069a2aed2b665bdff266` |
| Task | text-to-video (generator tower) |
| Precision | BF16 |
| Size / frames / fps | 1280 x 720 / 189 / 24 |
| Denoising steps | 35 |
| Guidance / flow shift / max seq len | 6.0 / 10.0 / 4096 |
| Output duration | 7.875 s per valid clip |
| Prompt and negative prompt | the model repo anchors `assets/example_t2v_prompt.json` and `assets/negative_prompt.json`; recorded by SHA-256, not reproduced here |
| Seeds | 17, 23, 41 (cycled evenly) |
| Guardrails | disabled for the topology cells; enabled cells are labeled |
| Endpoint | `POST /v1/videos/sync`, client and server sync timeout 5400 s |

The request uses multipart form data with the fields above plus
`extra_params={"use_resolution_template": false, "use_duration_template":
false, "guardrails": <posture>}` and the seed. `benchmark.py --dry-run` prints
the fixed fields, seed cycle, and timeout without reading prompt files.

## NVIDIA reference grid

NVIDIA's [Cosmos3-Super Generator benchmarks](https://github.com/NVIDIA/cosmos/blob/main/inference_benchmarks.md#cosmos3-super-generator)
document BF16, batch size one, matched prompts, seeds, and sampler settings, 189
frames at 24 fps, tensor parallelism for four- and eight-GPU configurations, and
engine-specific timing boundaries. The controls above make this repository's
topology cells comparable with one another. Concurrency-two confirmations are
labeled separately, and the same validity gate applies to every attempt. The
runtime and driver versions differ from NVIDIA's runs, so the published latency
grid is a contextual reference.

## Servers

Every service runs the pinned container `vllm/vllm-omni:cosmos3@
sha256:6d2630c7d637b699557573f2c3fee8df5d4d0cd718977aa22549ed6a6ef30587`,
which is vLLM-Omni with vLLM 0.25.0 inside, served from a loopback address on
the node.

- Full-node recommended service (H200 or B200): `serve-h200.sh` /
  `serve-b200.sh`. Flags:
  `--cfg-parallel-size 2 --ulysses-degree 4 --use-hsdp --hsdp-shard-size 8
  --init-timeout 1800` plus guardrail posture. This is the model card's
  recommended layout: CFG-2 (two guidance groups), Ulysses-4 (four-way sequence
  parallelism within each group), HSDP-8 (model state sharded across an
  eight-rank group). These are overlapping dimensions of the same eight GPUs,
  not replicas or a 64-GPU deployment.
- B200 topology cells: `serve-b200-replicas.sh`. Rendered as
  replicas x GPUs per replica. The 1 x 8 cell is the recommended hybrid layout;
  the 2 x 4, 4 x 2, and 8 x 1 cells use tensor parallelism inside each service
  (`--tensor-parallel-size 4 / 2 / 1`). Each replica is its own container, gets
  a disjoint GPU group and its own host port, and every cell fills the node.

Start replicas sequentially. The launcher waits for each replica to report
application readiness before starting the next. Measure one topology at a time
and begin only after every replica in that cell is ready.

## Timing boundary

Request latency is **client wall time** (dispatch to full response), reported
as median with mean, min, max, and p95 where the sample count supports it. Each
cell runs a measurement window: fully resident services, one warmup request per
replica excluded, window opened at first dispatch and closed at final
completion. The window includes request routing, generation, MP4 encoding,
replica skew, and any idle tail. It excludes service construction and model
load. The supplemental serving observations include server-side generation time
where it was recorded. The included benchmark records client wall time and
leaves the reserved server-generation field null. The two are never averaged
together.

Node throughput is duration of valid output divided by window time, normalized
to an hour: `generated video-seconds / node-hour`. Allocated GPU-hours are
`window hours x 8`; aggregate GPU-hours are never computed by summing request
wall times.

## Validity gate

An attempt counts as valid only if it:

1. returns HTTP 200 under the declared timeout,
2. produces a non-empty MP4 that decodes cleanly from first to last frame,
3. reports 1280 x 720, exactly 189 frames, 24 fps, and 7.80 to 7.95 seconds,
4. contains visible spatial detail and change across five sampled frames.

`validate-video.py` implements exactly this gate. Attempts that fail, are
refused, time out, or come back corrupt stay in the denominator, and the yield
is the fraction valid over attempted.

## Determinism and output identity

The supplemental observations found byte-identical output at a fixed seed within
one live server instance. Across a server restart, the H200 same-config median
PSNR band was 26.81-28.99 dB and the B200 band was 32.13-32.17 dB. Do not use
output identity across separate boots as a correctness signal.

## Concurrency

Request concurrency is requests in flight per service. It is distinct from
replica count (independent services) and from on-GPU parallelism (TP /
CFG / Ulysses / HSDP inside one service). Every topology cell ran at
concurrency one; the lowest-latency topology (1 x 8) and highest-throughput
topology (8 x 1) were then repeated at concurrency two. Throughput deltas under
5% were treated as an operational tie.

The later single-node consolidation ran all four topologies at both concurrency
levels on one node, and added a delayed repeat of the 1 x 8 cell at each
concurrency level to bound within-node run-to-run variance. Every concurrency-two
cell is bimodal, because the second request arriving at a service waits for the
first rather than overlapping with it, so that record summarizes latency by the
mean; a median falls in the gap between the two groups and describes no request
that ran.

## Result derivation

`results/b200-topology.json` embeds 147 sanitized production attempts, exact
window timestamps, and result values. The output SHA-256 in every embedded
attempt matched a source MP4 that passed `validate-video.py`.
`results/b200-single-node-20260831.json` embeds 240 attempts across ten cells
under the same rules. `derive-results.py` recomputes every cell aggregate and
comparison from the embedded inputs of either file. The H200 and B200 serving-envelope files are supplemental
observations whose raw per-request inputs are not included. Server logs,
telemetry, generated clips, prompt text, local paths, and infrastructure
identifiers are excluded.

## Exclusions

- Any replica baseline on H200 (not measured).
- The 4 x 2 topology at concurrency two (not measured).
- Ring parallelism greater than 1 (not tested).
- Semantic quality, human acceptance, and downstream utility. All throughput
  here counts technically valid output only.
- Transfer to other output shapes, models, or node counts.
- The reasoner tower and model-quality rankings.

## Reproduce

```bash
# 1. Start a full-node service (loopback)
bash reproduce/serve-h200.sh          # or serve-b200.sh
# or launch a topology on B200
TOPOLOGY=8x1 bash reproduce/serve-b200-replicas.sh

# 2. Inspect the request contract (no GPU)
python3 reproduce/benchmark.py --dry-run \
  --prompt <path>/assets/example_t2v_prompt.json \
  --negative-prompt <path>/assets/negative_prompt.json

# 3. Self-check the recording + derivation pipeline with no server (no GPU)
python3 reproduce/benchmark.py --fixtures

# 4. Run a cell (service must be resident first)
python3 reproduce/benchmark.py --host 127.0.0.1 --topology 1x8 \
  --prompt ... --negative-prompt ... --output ./bench-out \
  --attempts 24 --concurrency 1

# 5. Re-derive the aggregates
python3 reproduce/derive-results.py \
  ./bench-out/requests.jsonl ./bench-out/window.json

# 6. Verify the included B200 topology file
python3 reproduce/derive-results.py --verify-embedded results/b200-topology.json
```

Do not run a measured cell against a server that is still loading. Start, wait
for the service to report ready, run one warmup per replica, then open the
window.
