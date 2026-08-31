# Cosmos3-Super serving on one eight-GPU node

Reference implementation and measurement record for serving the NVIDIA
`nvidia/Cosmos3-Super` world foundation model generator tower (text to video) on
a **single eight-GPU H200 or B200 node** through the vLLM-Omni container. The
repository provides pinned launch scripts, a validated benchmark, rederivable
B200 and H200 topology results measured under one software stack, and
supplemental H200 and B200 serving observations.
Everything was measured in August 2026 on Nebius eight-GPU nodes. Measurements
are in `results/`, and the included derivation code is in `reproduce/`.

This repository covers only the generator serving path. The reasoner tower,
model-quality rankings, and any batch or lab tooling are out of scope.

## Tested operating decisions

The measurements support these operating decisions:

1. **Full-node recommended service.** The model card's recommended layout,
   CFG-2 x Ulysses-4 x HSDP-8, serves correctly on one eight-GPU H200 node and
   one eight-GPU B200 node with the pinned container. It is the fastest
   single-service arrangement measured. Start with `serve-h200.sh` or
   `serve-b200.sh`.
2. **B200 topology trades latency for throughput.** One node can run 1, 2, 4,
   or 8 independent services. The four arrangements were measured as sequential
   cells on one B200 node, with all replicas inside each cell active concurrently.
   Eight single-GPU services produce 42.5% more finished video per node-hour
   than one eight-GPU service, at 5.5 times the per-clip latency.
   Pick by objective (see the topology table). Use `serve-b200-replicas.sh`.
3. **Concurrency is queueing, replica count is throughput.** At a fixed
   topology, raising in-flight requests per service moves node throughput by a
   few percent and can add large latency. The recommended admission is
   concurrency one.

Every throughput number counts **technically valid** output: an HTTP 200 that
decodes as a complete MP4 at the requested shape. Semantic quality, human
acceptance, and downstream utility were not measured. These are not
accepted-output figures.

## Fixed workload

A fixed workload throughout: text to video, 1280 x 720, 189 frames, 24 fps,
35 denoising steps, guidance 6.0, flow shift 10.0, maximum sequence length
4096, and the model repository's anchor prompt and negative prompt. Each valid
clip is 7.875 seconds of video.

Timing boundary: request **client wall time** (round trip from dispatch to full
response), measured inside a run-level window. The window includes request
routing, generation, MP4 encoding, replica skew, and the idle tail until the
last attempt finishes. It excludes service construction and model load.
The supplemental serving observations include server-side generation time where
it was recorded. The included benchmark records client wall time and leaves its
reserved server-generation field null. The two timing boundaries are kept
separate.

Validity gate: an attempt counts only if it returns HTTP 200, produces a
non-empty MP4 that decodes cleanly, and reports 1280 x 720, 189 frames, 24 fps,
about 7.875 seconds. Without the gate a throughput number includes failures,
and on this model the failure modes are quiet: a 200 with a truncated file, or
a decodable file at the wrong shape.

### Relation to NVIDIA's benchmark grid

NVIDIA's [Cosmos3-Super Generator benchmarks](https://github.com/NVIDIA/cosmos/blob/main/inference_benchmarks.md#cosmos3-super-generator)
provide the reference grid for BF16, batch-size-one generation across one, four,
and eight GPUs. To make our topology cells comparable with one another, we fixed
35 denoising steps, guidance 6.0, flow shift 10.0, maximum sequence length 4096,
prompt hashes, the 17/23/41 seed cycle, guardrails off, and concurrency one per
service. We applied one video-validity gate to every attempt. The concurrency-two
confirmations are labeled separately.

These numbers and NVIDIA's grid were produced on different software. NVIDIA's
published figures come from an internal vLLM-Omni build that is not the public
container, at a different runtime version and on a different driver branch. The
numbers here come from the public `vllm/vllm-omni:cosmos3` image, pinned by
digest, which reports vLLM 0.25.0. Every other workload control we can compare
is aligned: model and revision, task, precision, resolution, frame count, frame
rate, denoising steps, guidance, flow shift, and guardrail posture. That leaves
the runtime version and the driver branch as the residual variables between the
two sets of figures. Neither has been measured as the cause of the difference,
and this repository does not claim it has. What the results here describe is the
public serving stack as an operator can obtain it, which is the stack to plan
against unless you have access to NVIDIA's internal build.

## Requirements

- One eight-GPU H200 (141 GB) or B200 (192 GB) node running Linux with the
  NVIDIA driver, NVIDIA Container Toolkit, and Docker with `--gpus` support.
- Python 3, `ffmpeg`, and `ffprobe` on the benchmark client.
- A gated-repo license accepted: `nvidia/Cosmos-1.0-Guardrail` on Hugging Face,
  and an `HF_TOKEN` for it (needed only with guardrails enabled; see below).
- Enough disk and time for the weights on first launch: the model snapshot is
  about 124 GB, and the guardrail repo is about 17 GB.

## Start a full-node H200 service

```bash
bash reproduce/serve-h200.sh
```

The script produces one service across all eight GPUs at the model card's
recommended layout. Guardrails are off by default. To enable them, accept the
guardrail repository terms, set `HF_TOKEN` in the environment, and run:

```bash
GUARDRAILS=1 bash reproduce/serve-h200.sh
```

The service binds to loopback.

## Start a full-node B200 service

```bash
bash reproduce/serve-b200.sh
```

Same shape: one service, all eight GPUs, recommended layout, loopback only.

## Choose a B200 topology

A node that costs the same per hour can run one eight-GPU service, two
four-GPU services, four two-GPU services, or eight single-GPU services. These
were measured sequentially on one B200 node, 24 production attempts per arrangement,
one request in flight per service, guardrails off, seeds 17/23/41 cycled
evenly. The unit that sets your cost is **finished video-seconds per
node-hour**, because every arrangement occupies the whole node.

| Arrangement | Mean per clip | Video-seconds / node-hour | vs 1 x 8 | Use it when |
| --- | ---: | ---: | ---: | --- |
| 1 service x 8 GPUs (recommended layout) | 68.5 s | 413.6 | baseline | A person is waiting on a result |
| 2 services x 4 GPUs (TP-4) | 121.5 s | 466.3 | +12.74% | Latency matters, throughput helps |
| 4 services x 2 GPUs (TP-2) | 212.4 s | 529.0 | +27.90% | Balance latency and node throughput |
| 8 services x 1 GPU (TP-1) | 378.1 s | 589.4 | +42.50% | Bulk offline generation, cost first |

Every row returned 24 valid clips out of 24. No arrangement dominates another:
throughput rises as GPUs per service fall, and latency rises with it. The 1 x 8
endpoint answers interactive demand; the 8 x 1 endpoint answers bulk volume.
These ten cells are in `results/b200-single-node-20260831.json`, measured on one
node under one driver and one container image. Because the node is the billing
unit, the cost per generated second is 11.3%, 21.8%, and 29.8% lower than
baseline at 1.77x, 3.10x, and 5.52x the baseline latency. These ratios hold at
any node rate. An earlier run of the same four arrangements, in
`results/b200-topology.json`, reproduced these figures within 1.4%.

Launch one topology on loopback. Stop it before launching a different topology:

```bash
TOPOLOGY=8x1 bash reproduce/serve-b200-replicas.sh
```

The launcher names containers `cosmos3-<topology>-r<index>`. Before switching
topologies, list the current containers with `docker ps --filter name=cosmos3-`
and remove the listed containers with `docker rm -f <name> ...`.

The 1 x 8 cell in that table uses the recommended hybrid layout; the multi
service cells use tensor parallelism inside each service. No cell leaves a GPU
idle.

## Choose an H200 topology

The same four arrangements were measured on one eight-GPU H200 node under the
same driver, the same container digest, and the same workload as the B200 cells,
so the two records differ in silicon rather than in software.

| Arrangement | Mean per clip | Video-seconds / node-hour | vs 1 x 8 | Share of matched B200 node output |
| --- | ---: | ---: | ---: | ---: |
| 1 service x 8 GPUs (recommended layout) | 123.3 s | 229.9 | baseline | 55.59% |
| 2 services x 4 GPUs (TP-4) | 230.0 s | 245.6 | +6.83% | 52.67% |
| 4 services x 2 GPUs (TP-2) | 416.5 s | 271.4 | +18.05% | 51.30% |
| 8 services x 1 GPU (TP-1) | 779.0 s | 289.1 | +25.75% | 49.05% |

Every row returned 24 valid clips out of 24, in
`results/h200-single-node-20260831.json`. Three things follow.

**The ordering is the same on both platforms.** Throughput rises as GPUs per
service fall, and the recommended full-node layout is the slowest arrangement by
node output on H200 exactly as it is on B200. An operator who picked a layout
from the B200 result would pick the same one on H200.

**The payoff is smaller.** Splitting the node from one service into eight buys
25.75% more node output on H200 against 42.50% on B200, and the cost per
generated second falls 20.5% against 29.8%. The latency price is higher too:
6.3 times baseline on H200 against 5.5 times on B200. Replica splitting is worth
less on Hopper than the B200 numbers alone would suggest.

**TP-1 fits.** A single H200 loads the model at 120.9 GiB against about 140.4
GiB usable, leaving roughly 19 GiB, so the eight-service arrangement is
measurable rather than blocked by memory. The Hopper operating point does not
invert to TP-2.

Across the four matched arrangements the H200 node delivers 49% to 56% of B200
node output at 1.80 to 2.06 times the request latency. The share falls as GPUs
per service fall, so the gap between the platforms is widest exactly where
throughput is highest.

## The request contract

The endpoint is `POST /v1/videos/sync`, with client and server sync timeout set
to 5400 seconds. A request carries the workload fields above as form data plus
the prompt and negative prompt (read from your local model files), a seed, and
`extra_params` that disable the resolution and duration templates. The response
is an MP4. `reproduce/benchmark.py --dry-run` prints the fixed request fields,
seed cycle, and timeout without reading prompt files or contacting a server.

## Image and model pinning

- Container: `vllm/vllm-omni:cosmos3`, pinned by digest
  `sha256:6d2630c7d637b699557573f2c3fee8df5d4d0cd718977aa22549ed6a6ef30587`
  (pushed 2026-07-20; the server inside reports vLLM 0.25.0).
- Model: `nvidia/Cosmos3-Super`, snapshot pinned by `--revision`
  `e0262be9d8f7586bc24c069a2aed2b665bdff266`.

The pinned container predates vLLM-Omni v0.26.0 (released 2026-08-03). The
scripts pin the tested image so the included measurements retain their recorded
software boundary. Treat results from a newer image as new measurements.

## Guardrail access and the Xet workaround

`nvidia/Cosmos-1.0-Guardrail` is a **gated** repository. The server pulls it at
startup when guardrails are on, so on a clean box the model card's published
command fails with a `GatedRepoError` until you accept the license on Hugging
Face under your own account and supply `HF_TOKEN`.

The pinned image also carries `huggingface_hub 1.23.0` plus `hf-xet 1.5.1`, a
pair that fails in the Xet download client with
`Unable to parse string as hex hash value`
([huggingface/xet-core#895](https://github.com/huggingface/xet-core/issues/895),
fixed after this image was pushed). The workaround is `HF_HUB_DISABLE_XET=1`.
Set it only when you need it (guardrails on), because disabling Xet changes the
download path. The scripts set it only for the guardrail-required path and
leave the environment otherwise untouched.

This repository ships guardrails **disabled** for the benchmark (the measured
topology cells are guardrails off and the timing boundary is stated for that
posture). If you enable guardrails, expect the cost to depend on content. On
the anchor prompt the measured overhead was about 18 seconds (about 15%) at
189 frames, but on a random-prompt benchmark cell it was only about 2 seconds
(roughly 2%), a roughly nine-fold swing driven by generated content. Report
guardrail overhead tied to your prompt, never as a constant.

## Startup behavior

The supplemental observations show that the recommended layout reaches ready in
about 5 minutes on both platforms with a warm disk cache. HSDP sharded startup
(all recommended-layout configurations) measures about 290 seconds warm; a pure
TP-8 service comes up in about 90 seconds because it has no HSDP shard load. A
cold page cache adds roughly 5 minutes on top, whichever config you run. The
server runs a dummy warm-up request automatically at startup; the first real
request after that is the one to measure.

## Concurrency behavior

Request concurrency is the number of requests in flight per service. Replica
count is the number of independent services, while TP, CFG, Ulysses, and HSDP
control parallelism inside one service. The supplemental serving observations
recorded this behavior:

- On the full-node H200 service at the production shape (guardrails on, random
  prompts, measured with vLLM-Omni's benchmark harness), raising concurrency
  from 1 to 8 moved throughput from 28.21 to 30.96 clips per hour, about +10%,
  while median latency grew roughly 7x. Peak GPU memory stayed within 2 MB
  across the cells, consistent with request queueing rather than batching.
- On one B200 service, raising concurrency from 1 to 2 moved throughput from
  49.06 to 54.99 clips per hour, about +12%, at a large latency cost.
- On the B200 topologies, doubling concurrency to two requests in flight per
  service raised node throughput by 3.2% on 1 x 8 and 0.4% on 8 x 1, while mean
  request latency rose 47.1% and 32.9%. Every concurrency-two cell is bimodal:
  the second request arriving at a service waits for the first, so the attempts
  fall into two groups with an empty gap between them, and latency for those
  cells is reported as the mean. On 8 x 1 the split is sixteen fast attempts and
  eight slow ones, so a median lands inside the fast group and reports a 0.5%
  cost while a third of the requests took about twice as long.
- On the H200 topologies the same thing happens, with the same shape: +1.4% node
  throughput at +48.8% mean latency on 2 x 4, and +0.5% at +49.6% on 4 x 2. Both
  cells split twelve and twelve, and the slow group runs 1.97 to 1.99 times the
  fast group.

For this workload and node shape, use concurrency one. Add replica services when
the objective is higher node throughput; the measured B200 topology increased
throughput by 42.50%, and the H200 topology by 25.75%.

## Video validity checks

`reproduce/validate-video.py` implements the strict gate used to revalidate the
147 embedded B200 topology outputs, the 240 embedded B200 single-node outputs,
and the 168 embedded H200 outputs, and applied by `benchmark.py` to new runs.
Every embedded attempt in all three files passed it.
The file must be a readable MP4 that decodes fully, reports 1280 x 720, 189
frames, 24 fps, about 7.875 seconds, and is not blank or frozen. The validator
exits nonzero and names the failing check if any part is off:

```bash
python3 reproduce/validate-video.py clip.mp4
```

Output is byte-reproducible **within one live server instance** (same seed, same
clip hashes), but a fixed seed does not reproduce across a server restart. On
H200 the same-config restart floor was a median PSNR band of 26.81 to 28.99 dB.
Do not use output identity across restarts as a correctness signal.

## Run the benchmark

`reproduce/benchmark.py` drives the validated cells and writes per-attempt
records to a directory you choose:

```bash
python3 reproduce/benchmark.py --output ./bench-out --host 127.0.0.1 --port 8000 \
  --prompt <path>/assets/example_t2v_prompt.json \
  --negative-prompt <path>/assets/negative_prompt.json
```

It supports `--dry-run` (prints the request contract, touches no GPU),
`--fixtures` (self-check on synthetic records, no GPU), and `--topology` to
select a replicate set. Each attempt records the request shape, prompt hash,
seed, steps, guardrail posture, start and finish timestamps, HTTP status,
client wall time, output byte count,
SHA-256, geometry, frame count, frame rate, decode status, and failure reason.
Failed attempts stay in the denominator. For node throughput the script uses
run-level window time, never the sum of per-request wall times.

## How the results are derived

`results/b200-topology.json` embeds 147 sanitized production attempts and exact
window timestamps. Each embedded output hash matches a source MP4 that passed
the strict validator in `reproduce/validate-video.py`. The JSON excludes prompt
text, output video, local paths, and infrastructure identifiers. Verify every
topology aggregate and comparison:

```bash
python3 reproduce/derive-results.py --verify-embedded results/b200-topology.json
```

`results/b200-single-node-20260831.json` embeds 240 sanitized production attempts
across ten cells under the same rules, and every attempt passed the strict
validator. Latency in that file is summarized by the mean rather than the median,
because each concurrency-two cell is bimodal: the second request arriving at a
service waits for the first, so a median falls in the gap between the two groups
and describes no request that ran. Verify it the same way:

```bash
python3 reproduce/derive-results.py --verify-embedded results/b200-single-node-20260831.json
```

`results/h200-single-node-20260831.json` embeds 168 sanitized production attempts
across seven cells on one H200 node, under the same rules and the same mean-based
latency reporting. Its comparison block also carries the cross-platform ratios
against the B200 single-node record, and `--verify-embedded` recomputes those
from both files rather than accepting them:

```bash
python3 reproduce/derive-results.py --verify-embedded results/h200-single-node-20260831.json
```

The H200 and B200 serving-envelope files and the two environment files are
supplemental observational summaries. Their raw per-request inputs are not
included and no command here rederives them, so `--verify-embedded` reports
`not_a_rederivable_record` and exits 2 on those four files rather than reporting
a pass over checks it did not run.

## Data handling and what is not included

The topology result publishes sanitized per-attempt measurement fields and
output SHA-256 values. Excluded material includes access and server logs,
generated videos, prompt text, host and tenant identifiers, node names, IP
addresses, object-storage names and paths, and authentication tokens. The
results reference prompts by hash without redistributing NVIDIA's prompt
assets. `PROVENANCE.md` covers the model, container, guardrail model, prompts,
and cited figures.

## Troubleshooting

- **`GatedRepoError 401/403`**: guardrails are on and the license or token is
  missing. Accept `nvidia/Cosmos-1.0-Guardrail` on Hugging Face, set `HF_TOKEN`,
  or launch with guardrails off.
- **`Unable to parse string as hex hash value` at startup**: the Xet client
  pair in the pinned image failed. Set `HF_HUB_DISABLE_XET=1` for that launch.
- **Container exits 1 at startup**: check the guardrail and Xet conditions first;
  this is the common cause on a clean node.
- **Sync request returns 504 after many minutes**: at this shape a full
  generation can exceed the default 600-second window. The 5400-second sync
  timeout is set by the scripts; confirm your client honors it.
- **Two same-seed runs differ**: expected across separate boots. It is the
  restart floor, not a failure. Within one running instance the same seed
  reproduces.
- **A clip will not decode**: a 200 with a truncated MP4 is the quiet failure
  this package checks for. Run `validate-video.py`; if it fails, that attempt
  does not count toward throughput.

## Serving only on loopback

All reproduce scripts bind the API server to `127.0.0.1`. That is by design:
the reference here is a local, benchmarkable service. If you expose it beyond
the node, you must put it behind authenticated TLS ingress that you operate and
that terminates TLS with client authentication at the boundary. That ingress is
operator-owned and is not implemented, configured, or implied by this
repository. No command here opens a firewall port, edits a security group, or
adds an unauthenticated public listener.

## Results

- `results/h200-environment.json`, `results/h200-serving-envelope.json`:
  H200 node, the recommended-service latency envelope, the TP-8 control, the
  concurrency envelope, and the determinism band.
- `results/b200-environment.json`, `results/b200-serving-envelope.json`:
  B200 node, the recommended-service anchors, the recommended-versus-TP-8 pair,
  the 1/4/8 ladder, and the concurrency spot-check.
- `results/b200-topology.json`: the four sequential topology cells, the
  concurrency-two confirmation, and the drift check.
- `results/b200-single-node-20260831.json`: all ten cells of the single-node
  consolidation measured on one B200 node under one driver and one image, being
  the four concurrency-one arrangements, their four concurrency-two counterparts,
  and two delayed repeats that bound within-node run-to-run variance.
- `results/h200-single-node-20260831.json`: the matching seven cells on one H200
  node under the same driver, container digest, and workload, being the four
  arrangements, two concurrency-two counterparts, and one delayed repeat, plus
  the cross-platform ratios against the B200 single-node record.
- `results/SHA256SUMS`: checksums over the seven JSON files in `results/`.

## Methodology

Full method, exact flags, the launch commands, and the measurement boundaries
are in `reproduce/METHOD.md`. Rights and ownership are in `PROVENANCE.md`.
