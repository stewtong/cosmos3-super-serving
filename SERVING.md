<!-- register: public operations guide | reader: GPU inference operators | consumed: terminal alongside deployment -->

# Operate the node-local Cosmos3-Super service

`bin/cosmos3-super` launches one complete eight-GPU topology and exposes one loopback endpoint. Profile mappings, image and model pins, ports, queue limits, timeouts, server flags, and evidence cells come from [`config/profiles.json`](config/profiles.json).

## Profiles map to measured topologies

| Profile | Replicas | GPUs per replica | Parallel configuration | Default admission |
| --- | ---: | ---: | --- | --- |
| `latency` | 1 | 8 | CFG parallel 2, Ulysses 4, HSDP shard 8, Ring 1 | 1 active request per replica |
| `balanced` | 4 | 2 | Tensor parallel 2 | 1 active request per replica |
| `throughput` | 8 | 1 | Tensor parallel 1 | 1 active request per replica |

The 2 replicas x 4 GPUs, tensor-parallel-4 topology is available through `--topology 2x4`.

```bash
bin/cosmos3-super serve --platform b200 --profile throughput
bin/cosmos3-super serve --platform h200 --profile latency
bin/cosmos3-super serve --platform b200 --topology 2x4
```

The launcher refuses a platform mismatch, any GPU count other than eight, an occupied port, an existing deployment state file, a topology that does not fill the node, a backend that exits during startup, or a readiness timeout. A no-GPU dry run resolves the same configuration without contacting Docker:

```bash
bin/cosmos3-super serve --platform h200 --profile balanced --dry-run
```

## Startup is sequential and observable

Backend ports begin at `127.0.0.1:8100`. Replicas start one at a time to reduce model-load contention. The launcher waits for `Application startup complete` before starting the next replica. After all replicas are ready, it starts the router on `127.0.0.1:8000` and waits for healthy capacity.

The launcher writes sanitized state and manifest files under `/var/tmp/cosmos3-super/`:

- `deployment.json` supports lifecycle ownership and status;
- `launch-manifest.json` records the resolved profile, topology, GPU groups, ports, image digest, model revision, flags, readiness timestamps, queue policy, and timeouts;
- `router.log` records node-local router events without prompt or response bodies.

Set `COSMOS3_SUPER_RUNTIME_DIR` or pass the global `--runtime-dir` option to move this state:

```bash
bin/cosmos3-super --runtime-dir /run/user/$(id -u)/cosmos3-super status
```

## Admission stays at one active request per replica

The router selects a healthy idle replica in deterministic round-robin order. Every backend has a one-slot semaphore. Waiting requests enter a node-level queue with an explicit size and timeout.

Multipart request bodies are capped at 16 MiB. Responses are spooled and spill to a temporary file above 16 MiB, then stream to the client without retaining an additional full response copy in memory.

| Condition | HTTP result | Router action |
| --- | ---: | --- |
| Idle healthy replica exists | backend status | Forward once to that replica |
| Healthy replicas are busy and queue has room | pending | Wait until capacity or queue timeout |
| Queue is full | 429 | Reject before backend dispatch |
| Queue wait expires | 504 | Reject before backend dispatch |
| Every replica is unavailable | 503 | Reject before backend dispatch |
| Backend fails after dispatch | 502 | Report failure without replay |

Automatic replay after dispatch can duplicate a long generation when completion is ambiguous. The router retries selection only before dispatch.

Queue defaults are eight waiting requests and 900 seconds. Generation timeout is 5400 seconds. Override queue settings at launch:

```bash
bin/cosmos3-super serve --platform b200 --profile throughput \
  --queue-limit 16 --queue-timeout 600
```

Changing queue settings does not change the one-active-request limit. Any future higher-admission mode must carry an experimental label and new measurements.

With the default queue limit, a synchronized saturation control can hold eight active and eight queued requests. A seventeenth concurrent request then receives HTTP 429 before backend dispatch. This ordinal behavior depends on the first sixteen requests still occupying the active and queued slots.

## Health removes failed replicas from admission

The router probes each backend's application-level `/health` endpoint. An unhealthy replica receives no new work and reduces reported capacity. Existing work is allowed to finish or fail under the backend timeout. Replacement remains an operator action; the router does not hide repeated crashes behind a restart loop.

The loopback status endpoints are:

| Endpoint | Content |
| --- | --- |
| `GET /healthz` | Aggregate healthy capacity; returns non-success when all replicas are unavailable |
| `GET /status` | Profile, topology, policy, queue state, counters, and per-replica health and activity |
| `GET /metrics` | The same bounded JSON metrics for node-local collection |

Status and metrics exclude prompt text, negative-prompt text, output content, access tokens, cache paths, internal backend addresses, and infrastructure identifiers.

## Lifecycle targets only the owned deployment

```bash
bin/cosmos3-super status
bin/cosmos3-super stop --dry-run
bin/cosmos3-super stop
```

Each backend container carries `io.cosmos3-super.run=<run-id>` and `io.cosmos3-super.role=backend`. `stop` resolves containers with the exact run label and verifies that the recorded PID command contains the matching router run ID. It prints those targets before signaling or removing them. A missing or mismatched router process blocks the signal rather than falling back to name matching.

Starting another deployment while `deployment.json` exists fails. Stop the recorded deployment first. If state is lost, inspect Docker labels directly and resolve the exact run ID before taking action.

## Guardrails require gated model access

The benchmark-backed profiles run with guardrails disabled. Enable guardrails with:

```bash
HF_TOKEN=... bin/cosmos3-super serve --platform h200 --profile latency --guardrails
```

The operator must accept the `nvidia/Cosmos-1.0-Guardrail` terms through their own Hugging Face account. The pinned image carries the `huggingface_hub 1.23.0` and `hf-xet 1.5.1` combination affected by `huggingface/xet-core#895`, so the launcher supplies `HF_HUB_DISABLE_XET=1` only on this path. It passes the name `HF_TOKEN` into Docker without recording or printing its value.

Guardrail cost is content-dependent. The supporting measurements are in [`OBSERVATIONS.md`](OBSERVATIONS.md); they do not change the guardrails-disabled topology claims.

## Loopback is the security boundary

The router and backends bind to `127.0.0.1`. This repository does not supply public ingress, TLS termination, authentication, tenant isolation, request authorization, quotas, abuse prevention, or a distributed control plane. An operator exposing the service beyond the node must add authenticated TLS ingress and production policy outside this process.
