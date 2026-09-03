<!-- register: public supporting evidence note | reader: performance engineers | consumed: GitHub evidence review -->

# Supporting serving observations

These measurements cover startup, guardrails, determinism, and comparison with NVIDIA's published benchmark. Their controls differ from the main 17-cell study, and several include aggregate summaries without raw request records. They do not add cells to the main study or change the profile claims.

## Startup depends on parallel layout and cache state

The full-node hybrid configuration reached application readiness in about 280 to 290 seconds with a warm disk cache on H200. Pure TP-8 reached readiness in about 90 seconds because it did not perform the HSDP shard-load path. A cold H200 page cache added about 320 seconds. One validated serving-container run reached readiness in 592 seconds from cold cache.

The launcher default allows 2,400 seconds for each replica because cache state and storage performance can move startup materially. Readiness means the vLLM-Omni application reported complete startup; it does not include a production warmup request.

Sources: [`results/h200-serving-envelope.json`](results/h200-serving-envelope.json) and the environment records in [`results/`](results/).

## Guardrail cost is content-dependent

On the H200 full-node hybrid service at 189 frames and 35 steps:

| Prompt source | Guardrails off | Guardrails on | Added server generation time |
| --- | ---: | ---: | ---: |
| Anchor prompt | 120.57 s | 139.01 s | 18.4 s, 15.3% |
| Random-prompt benchmark cell | approximately 120 s | approximately 122 s | about 2 s, 1.7% |

The measured overhead differed by about ninefold between these prompt sources. Report guardrail cost with the prompt and output conditions that produced it. Enabling guardrails also changes output bytes relative to a guardrails-disabled run.

The guardrail repository is gated. The pinned image contains `huggingface_hub 1.23.0` and `hf-xet 1.5.1`, the combination affected by [`huggingface/xet-core#895`](https://github.com/huggingface/xet-core/issues/895). The launcher supplies `HF_HUB_DISABLE_XET=1` only when guardrails are enabled.

Source: [`results/h200-serving-envelope.json`](results/h200-serving-envelope.json).

## Fixed seeds reproduce within one live server instance

Repeated requests at a fixed seed produced byte-identical MP4 hashes within one live server instance. The same seed did not reproduce byte-identically across a server restart.

| Platform | Same-configuration restart PSNR median band |
| --- | --- |
| H200 | 26.81 to 28.99 dB across four restart crossings |
| B200 | 32.13 to 32.17 dB across two restart crossings |

The platform-specific bands differ. Output identity across separate boots is therefore unsuitable as a correctness gate. The primary study uses structural and decode validity for each output; it does not compare pixels across topology restarts.

Sources: [`results/h200-serving-envelope.json`](results/h200-serving-envelope.json) and [`results/b200-serving-envelope.json`](results/b200-serving-envelope.json).

## Hybrid and TP-8 differ on the same host

On one H200 node, the hybrid CFG-2, Ulysses-4, HSDP-8 layout measured 120.57 seconds of server generation at 35 steps against 131.26 seconds for TP-8. At 50 steps, the same comparison was 166.26 against 181.31 seconds. The hybrid layout was about 9% faster at both step counts.

Additional B200 measurements on the same node recorded 35-step client wall times of 68 to 70 seconds for the hybrid layout and 77 to 78 seconds for TP-8. The 50-step comparison was 91 against 104 seconds. These measurements are separate from the main 408-attempt study.

## NVIDIA's published benchmark uses a different runtime boundary

NVIDIA's [`Cosmos3-Super Generator benchmarks`](https://github.com/NVIDIA/cosmos/blob/f9c425669bffd2bf910067fbef7e0d5d8240fa84/inference_benchmarks.md#cosmos3-super-generator) report B200 text-to-video latency of 390.28, 113.31, and 62.11 seconds at one, four, and eight GPUs. The additional B200 measurements recorded 377, 122, and 77.3 seconds at the same nominal shape through the pinned public `vllm/vllm-omni:cosmos3` image.

The NVIDIA values came from an internal vLLM-Omni build on a different driver branch. The public image reports vLLM 0.25.0. The one-GPU, four-GPU, and eight-GPU differences were respectively 3.4% lower, 7.7% higher, and 24.5% higher latency in the public-stack observations. Neither runtime version nor driver branch was isolated as the cause.

The repository's profile decisions use the internally controlled B200 and H200 topology records, not the cross-runtime grid comparison.

## Additional concurrency tests show queueing behavior

The H200 full-node service used random prompts with guardrails enabled. Raising in-flight requests from one to eight moved throughput from 28.21 to 30.96 clips per hour while mean latency rose from 127.6 to 729.0 seconds. Peak memory stayed within 2 MB across the measurements, consistent with queueing rather than on-GPU batching.

The additional B200 full-node measurements moved from 49.06 to 54.99 clips per hour between concurrency one and two under guardrails. The main topology records provide the matched guardrails-disabled comparisons used for admission policy; those values are in [`BENCHMARKS.md`](BENCHMARKS.md).

## Evidence limits

The two supporting serving JSON files contain aggregate summaries without every per-request input. They return exit code 2 under `derive-results.py --verify-embedded`. The main topology records embed their attempts and timing windows and remain the authority for profile latency, node throughput, concurrency, repeats, and cross-platform claims.
