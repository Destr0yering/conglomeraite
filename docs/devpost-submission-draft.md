# Devpost submission draft

Prepared on 2026-07-18 from the live QwenCloud hackathon submission fields. Replace every bracketed placeholder and remove all drafting notes before submission.

## Project record

**Name:** The ConglomerAIte™

**Tagline:** Fault-tolerant Qwen swarm intelligence that self-corrects to 10/10 and keeps working at the edge.

**Built with:** Python, QwenCloud, qwen-plus, NVIDIA Jetson Orin Nano, llama.cpp, systemd, tegrastats, Alibaba Cloud Function Compute, Serverless Devs, HMAC-SHA256

**Repository URL:** https://github.com/Destr0yering/conglomeraite

**Video:** `artifacts/conglomeraite-demo.mp4` is a narrated 2:55 public-repository artifact with the Microsoft Andrew neural male voice and a 14-second physical Jetson network-link-loss insert. `[PENDING: YouTube or Vimeo mirror URL for the Devpost embed field]`

**Devpost project:** https://devpost.com/software/the-conglomeraite (project ID 1349485; public, but not entered into or submitted to the hackathon)

**Thumbnail:** `artifacts/architecture-diagram.png` (uploaded to the live Devpost project)

## Main description

### Inspiration

Cloud agents often fail at exactly the wrong moment: a field device loses connectivity, latency spikes, or a long refinement loop exhausts edge memory. The ConglomerAIte™ treats those failures as first-class operating conditions. It combines QwenCloud reasoning with a bounded Jetson fallback so an agent can return the best safe result available instead of hanging, retrying forever, or crashing the edge node.

### What it does

ConglomerAIte is an edge-native Generator/Critic system built primarily for Track 5: EdgeAgent, with Track 3: Agent Society mechanics. A Generator produces a candidate, an independent Critic returns a machine-parseable score and targeted corrections, and the system revises until a structurally valid 10/10 has no blocking issues. The loop also stops honestly on iteration, time, stagnation, provider, or hardware-safety boundaries and returns the best candidate seen.

When cloud use is allowed, the router targets QwenCloud's OpenAI-compatible endpoint. Retryable connectivity failures open a bounded circuit breaker and move subsequent work to the Jetson's loopback-only SYSOP Qwen Bridge. On edge, Generator and Critic are logical roles sharing one quantized Qwen-family model sequentially, avoiding duplicate weights and KV caches on the 8 GB Orin Nano. Metadata-only traces record routing, latency, tokens, scores, memory observations, and stop reasons without storing prompts or model output in the journal.

### How it was built

The dependency-light Python core contains provider adapters, retry classification, a three-state failover router, strict Critic-schema validation, best-candidate retention, score-stagnation detection, and RAM guards using tegrastats, `/proc/meminfo`, finite cgroup limits, and optional NVML away from Jetson. Systemd units isolate the orchestrator and model service, while a staged SSH/rsync deployment supports atomic activation and rollback. An HMAC-verified Alibaba Function Compute receiver accepts only redacted scalar telemetry.

### Evidence and results

One paid QwenCloud development run demonstrated an 8/10 first draft reaching structurally valid 10/10 consensus in two rounds. A three-task pilot observed lower latency and fewer output tokens than a budget-matched single-agent self-refiner on quality-noninferior cases, but it did not establish a general quality advantage: one task regressed by one evaluator point and the evaluator was not independent. On the deployed Jetson, a zero-paid forced-loss task made three route attempts, degraded twice to the local SYSOP bridge, retained its best 8/10 candidate, and stopped at the 125.7-second safety boundary with both services healthy and zero model restarts. The live Alibaba Function Compute receiver separately returned `200` for health, `401` for unsigned metadata, and `202` for one signed metadata-only event. Raw, sanitized summaries and claim limits are committed under `evidence/`.

### Challenges and lessons

Jetson CPU and GPU share unified memory, so NVMe swap is not extra GPU memory and `MemoryMax` is not a CUDA reservation. This led to a layered safety design: application-level admission checks, one-slot inference, bounded context/output, systemd containment, and explicit terminal results. Live testing also exposed two correctness problems—rubric drift and hidden output truncation—which were fixed by propagating the immutable rubric on every round and refusing truncated generations as consensus candidates.

### What is next

The production roadmap adds a durable round ledger and reboot resume, thermal/swap-growth guards, adaptive context shrinking, independent/blinded evaluation, and signed remote policy. Alibaba deployment proof is complete; the immediate submission work is to mirror the finished short demo on YouTube or Vimeo and complete the entrant-only fields.

## Required custom fields

| Devpost field | Draft answer / action |
| --- | --- |
| Submitter type | `[USER INPUT: Individual, Team, or Organization]` |
| Organization name | `[USER INPUT or leave blank]` |
| Country of residence | `[USER INPUT for every team member]` |
| Newly built or existing | `[USER INPUT: New or Existing]` |
| Start date (MM-DD-YY) | `[USER INPUT]` |
| Updates since May 26 | If Existing, describe only the significant post-May-26 work. If New, enter `Not applicable — project started during the submission period.` |
| Track | `Track 5: EdgeAgent` |
| Repository URL | `https://github.com/Destr0yering/conglomeraite` |
| Proof code URL | `https://github.com/Destr0yering/conglomeraite/blob/codex/hackathon-mvp/src/conglomeraite/config.py` shows the QwenCloud base URL. `https://github.com/Destr0yering/conglomeraite/blob/codex/hackathon-mvp/cloud/alibaba-telemetry/app_tiny.py` is the deployed Workbench receiver, and `evidence/alibaba-function-compute.summary.json` records the sanitized live verification. |
| Architecture diagram | Upload `docs/architecture-diagram.svg`. |
| Alibaba deployment screenshot | Upload `artifacts/alibaba-function-workbench-proof.png`, `artifacts/alibaba-function-trigger-endpoint-proof.png`, and `artifacts/alibaba-function-trigger-auth-proof.png`. |
| Blog/social URL | Optional; required only for the blog bonus prize. |
| AI tools used | `OpenAI Codex assisted with architecture review, implementation, test design, and documentation. QwenCloud qwen-plus powered the application's Generator/Critic development evidence. All deployment decisions, claims, and final submission materials were reviewed and controlled by the entrant.` |
| Learning derived | Suggested: `Significant` — user must choose. |
| Age check | `[USER MUST CONFIRM]` |
| Country check | `[USER MUST CONFIRM]` |
| Employee/conflict check | `[USER MUST CONFIRM]` |
| Testing instructions | Use the draft below. |

## Testing instructions draft

No paid API credential is required for repository validation:

```bash
python scripts/validate_offline.py
```

This command removes Qwen/DashScope credentials from its child-process environment, forces offline configuration, runs 49 deterministic core tests, runs three Function Compute receiver tests, and compiles the Python source. GitHub Actions runs the same credential-free validation on Windows and Ubuntu. The working edge behavior and physical-device execution are shown in the public demo video. Sanitized development evidence is under `evidence/`; architecture and deployment instructions are under `docs/`, `systemd/`, `deploy/`, and `cloud/alibaba-telemetry/`.

The target-device evidence is a metadata-only record at `evidence/nano-outage-demo.summary.json`; it contains no prompt, draft, hostname, IP address, API key, or reusable secret. No public SSH access is provided to the physical edge node.
