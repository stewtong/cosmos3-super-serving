<!-- register: public provenance record | reader: repository users and reviewers | consumed: rights and evidence audit on GitHub -->

# Provenance and rights

This repository distributes repository-authored code and prose plus sanitized factual measurement records. It excludes model weights, container layers, prompt text, generated videos, guardrail weights, server logs, credentials, and infrastructure identifiers.

## Repository-authored material uses Apache License 2.0

Repository-authored code, prose, and sanitized records are licensed under the [Apache License 2.0](LICENSE). Third-party materials retain their own terms; the repository license does not replace or expand them.

## Model and guardrail terms are third-party terms

The scripts reference [`nvidia/Cosmos3-Super`](https://huggingface.co/nvidia/Cosmos3-Super) at revision `e0262be9d8f7586bc24c069a2aed2b665bdff266`. NVIDIA publishes the model under [OpenMDW 1.1](https://openmdw.ai/license/1-1/). The license states that model outputs have no restrictions under that license. User inputs, third-party material, privacy, publicity, and applicable law can impose separate obligations.

Guardrails use the gated [`nvidia/Cosmos-1.0-Guardrail`](https://huggingface.co/nvidia/Cosmos-1.0-Guardrail) repository. Operators must accept its terms and obtain access through their own Hugging Face account.

The benchmark reads `assets/example_t2v_prompt.json` and `assets/negative_prompt.json` from the operator's local model snapshot. Public records contain normalized SHA-256 values, never prompt text.

## The serving container is referenced by digest

The launcher pulls `vllm/vllm-omni:cosmos3` at digest `sha256:6d2630c7d637b699557573f2c3fee8df5d4d0cd718977aa22549ed6a6ef30587`. The image is published by the vLLM-Omni project. vLLM-Omni source is distributed under the [Apache License 2.0](https://github.com/vllm-project/vllm-omni/blob/main/LICENSE). This repository does not redistribute the image or its layers.

## Primary records contain 408 sanitized attempts

The primary evidence is:

| Record | Cells | Attempts | Collection scope |
| --- | ---: | ---: | --- |
| `results/b200-single-node-20260831.json` | 10 | 240 | one eight-GPU B200 node, collected across two sessions under one driver and image |
| `results/h200-single-node-20260831.json` | 7 | 168 | one eight-GPU H200 node, one matched driver and image |

Every embedded attempt includes request timestamps, client wall time, HTTP status, output byte count and hash, prompt hashes, seed, replica, technical-validity result, and failure reason. Each cell includes its production window and derived aggregate. Source MP4 hashes were matched to files that passed `reproduce/validate-video.py`. All 408 primary attempts passed.

`results/b200-topology.json` contains an earlier 147-attempt B200 study across seven cells. It corroborates the topology ordering and is excluded from the primary count.

The B200 and H200 serving-envelope files are supplemental aggregate summaries. Their raw per-request inputs are absent, so the repository marks them as observational rather than rederivable.

## The public v1 runner now matches the source measurement boundaries

The canonical August 31 records were collected by a source runner that:

- stripped leading and trailing whitespace from both prompt files before hashing and sending them;
- dispatched synchronized rounds across every replica in the active topology;
- timed each request through complete MP4 persistence;
- closed the production window after the final response;
- applied technical video validation outside that request window.

`reproduce/benchmark.py` implements those boundaries as protocol v1. It records response-completion and validation timestamps separately and preserves failed attempts in the window and denominator.

`reproduce/benchmark-v2.py` measures the node-local routed endpoint through a work-conserving closed loop. V2 writes a distinct comparison basis. It has no claim on the historical v1 results until new dated measurements are collected.

`results/runtime-validation-20260903.json` is a sanitized live H200 operability record. It names runtime commit `90c66cc`. The publication candidate retains identical `bin/`, `serving/`, and `config/` content; later commits add documentation, evidence, and benchmark-client changes. The record contains profile and control verdicts, output hashes, and technical dimensions while excluding smoke-test timing from performance evidence. Prompt text, generated media, logs, infrastructure identifiers, local paths, process IDs, and container IDs remain outside the repository.

## Generated tables trace to embedded records

`reproduce/render-benchmarks.py` reads the two primary records and earlier B200 record to produce `BENCHMARKS.md`. Check mode compares the committed document byte for byte with a fresh rendering and recomputes displayed ratios from the cell aggregates.

`reproduce/derive-results.py` independently rederives each cell aggregate and record comparison from embedded attempts and windows. Result-file hashes are listed in `results/SHA256SUMS`.

## NVIDIA figures remain attributed material

NVIDIA comparison figures are attributed to the immutable [`NVIDIA/cosmos` benchmark revision](https://github.com/NVIDIA/cosmos/blob/f9c425669bffd2bf910067fbef7e0d5d8240fa84/inference_benchmarks.md#cosmos3-super-generator). They remain NVIDIA material and are not redistributed as source records here.
