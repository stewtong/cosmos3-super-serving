# Provenance and rights

This repository distributes original code, prose, and sanitized factual
measurement records. It does not distribute model weights, container layers,
prompt text, generated video, guardrail weights, or NVIDIA benchmark files.

## Repository content

Repository-authored code, prose, and sanitized measurement records remain
under default copyright, with all rights reserved. Permission is required from
the copyright holder to copy, modify, or redistribute that material.
Third-party materials linked below remain under their original terms and are
not redistributed by this repository.

## Model

The scripts reference [`nvidia/Cosmos3-Super`](https://huggingface.co/nvidia/Cosmos3-Super)
at a recorded revision. NVIDIA publishes it under
[OpenMDW 1.1](https://openmdw.ai/license/1-1/). The license states that model
outputs have no restrictions under that license. Other rights can still apply
to user inputs, third-party material, privacy, publicity, or applicable law.

## Serving container

The scripts pull the
[`vllm/vllm-omni:cosmos3`](https://hub.docker.com/r/vllm/vllm-omni) container
by digest. The image is published by the vLLM-Omni project. vLLM-Omni source is
distributed under the
[Apache License 2.0](https://github.com/vllm-project/vllm-omni/blob/main/LICENSE).
This repository does not redistribute the image or its layers.

## Guardrail model

Guardrails use the gated
[`nvidia/Cosmos-1.0-Guardrail`](https://huggingface.co/nvidia/Cosmos-1.0-Guardrail)
repository. The operator must accept its terms and supply access through their
own Hugging Face account. This repository does not redistribute those weights.

## Prompt assets

The benchmark reads `assets/example_t2v_prompt.json` and
`assets/negative_prompt.json` from the operator's local model snapshot. The
public records contain hashes of those files, not their text.

## NVIDIA reference figures

Any NVIDIA comparison figures are attributed to
[`NVIDIA/cosmos` inference_benchmarks.md](https://github.com/NVIDIA/cosmos/blob/main/inference_benchmarks.md#cosmos3-super-generator).
They remain NVIDIA material and are not licensed by this repository.

## Measurement provenance

The H200 and B200 serving observations were recorded on Nebius eight-GPU nodes
in August 2026. The H200 concurrency cells used the vLLM-Omni benchmark harness.
The B200 topology cells used a multi-endpoint runner against the same sync
endpoint. `results/b200-topology.json` contains 147 sanitized production
attempts, exact windows, and derived values, and
`results/b200-single-node-20260831.json` contains 240 more from the later
single-node consolidation on one B200 node, and
`results/h200-single-node-20260831.json` contains 168 from the matching H200
ladder measured under the same driver, container digest, and workload. The corresponding MP4 hashes were
matched to source clips that passed `reproduce/validate-video.py`. Prompt text,
generated clips, logs, local paths, host identifiers, network addresses, tenant
identifiers, and credentials are not distributed.

The H200 and B200 serving-envelope files are supplemental observational
summaries. Their raw per-request inputs are not included and cannot be rederived
from the repository contents.
