# The ConglomerAIte™

**Fault-Tolerant Swarm Intelligence & 10/10 Refinement**

![The ConglomerAIte edge-cloud Generator/Critic feedback loop](docs/assets/conglomeraite-devpost-thumbnail.png)

ConglomerAIte is an edge-native Generator/Critic workflow for the QwenCloud Global AI Hackathon. Its CLI accepts SYSOP-style task envelopes and routes primary reasoning to QwenCloud or, on the target NVIDIA Jetson Orin Nano 8 GB, through the existing advisory-only SYSOP Qwen Bridge. Direct task dispatch from the broader SYSOP Workflow Engine remains a deployment integration step.

The system does not promise that every task will reach a perfect answer. It enforces a **bounded 10/10 protocol**: generate, independently critique, revise, and stop only on structurally valid 10/10 consensus—or on an explicit iteration, time, stagnation, provider, or hardware-safety boundary.

## Why it fits the hackathon

- **Track 5 — EdgeAgent (primary):** cloud/edge routing, forced-offline operation, local-only inference, metadata-only traces, and graceful degradation during network failure.
- **Track 3 — Agent Society (differentiator):** isolated Generator and Critic roles, a fixed quality contract, explicit disagreement/refinement, and reproducible comparison against a single-agent baseline.
- **Evidence-ready implementation:** QwenCloud's OpenAI-compatible endpoint is visible in source/config; the service and deployment files are designed for the Orin's shared-memory constraints. A real Alibaba deployment, target-device run, and screenshots are still required submission evidence.

Devpost currently permits one track selection in the submission form. Select Track 5 and describe the Track 3 mechanics in the project narrative. See [the live-submission checklist](docs/submission-checklist.md).

## Architecture

In the intended integration, SYSOP submits a task and policy to the ConglomerAIte CLI boundary. Healthy requests use QwenCloud; retryable network/API failures open a cooldown circuit and route the same role call to the loopback-only local endpoint. Generator and Critic execute sequentially on the edge. The reference guard refuses to schedule another call when sampled RAM crosses a hard threshold, while systemd limits contain memory charged to each cgroup. Neither mechanism guarantees prevention of a sudden in-call CUDA/driver OOM.

See [the full architecture blueprint](docs/architecture.md) for the routing state machine, data contracts, failure semantics, privacy boundary, 10/10 sequence, and measurement design. The submission-ready visual is [docs/architecture-diagram.svg](docs/architecture-diagram.svg).

Observed MVP results—including a live 8/10 → 10/10 QwenCloud run, the honest three-task baseline pilot, and a Nano SYSOP-bridge smoke test—are recorded in [docs/mvp-results.md](docs/mvp-results.md).

## Quick start

Requirements: Python 3.10+ and an OpenAI-compatible Qwen endpoint. The package itself has no mandatory third-party runtime dependencies.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp config/conglomeraite.example.json config/conglomeraite.json
export QWEN_API_KEY='set-this-outside-the-repository'
conglomeraite --config config/conglomeraite.json \
  --trace-file artifacts/first-run.json \
  'Produce a safe recovery plan for an unhealthy edge service.'
```

On Windows PowerShell, activate with `.\.venv\Scripts\Activate.ps1` and set the key with `$env:QWEN_API_KEY = '...'`.

Run locally without attempting QwenCloud:

```bash
conglomeraite --config config/conglomeraite.example.json --offline \
  'Summarize the current edge health and propose one bounded action.'
```

Machine-readable output and a privacy-safe trace:

```bash
conglomeraite --json --trace-file artifacts/run.json 'Your task here'
```

The trace omits task, draft, and critique text. It retains provider choice, failover state, latency, token counts when supplied, memory snapshots, iterations, and the stop reason.

The portable example configuration allows cloud-backed development on a laptop without Jetson telemetry. The edge systemd configuration deliberately enables `monitor_required`; production runs on the Nano therefore fail closed when no unified-memory source is available.

## Configuration

Configuration precedence is JSON, then environment, then CLI overrides. Start with [`config/conglomeraite.example.json`](config/conglomeraite.example.json).

| Variable | Purpose |
| --- | --- |
| `QWEN_API_KEY` or `DASHSCOPE_API_KEY` | QwenCloud credential; never commit it |
| `CONGLOMERAITE_QWEN_ENDPOINT` | Primary OpenAI-compatible base URL |
| `CONGLOMERAITE_QWEN_MODEL` | Primary Qwen model name |
| `CONGLOMERAITE_LOCAL_KIND` | `openai` for direct llama.cpp or `sysop_bridge` for SYSOP `/qwen/agent` |
| `CONGLOMERAITE_LOCAL_ENDPOINT` | Local llama.cpp-compatible base URL |
| `CONGLOMERAITE_LOCAL_MODEL` | Qwen-family local model alias |
| `CONGLOMERAITE_OFFLINE` | Force local-only routing |

The official hackathon base URL is already the default:

```text
https://dashscope-intl.aliyuncs.com/compatible-mode/v1
```

The portable local default is loopback-only llama.cpp:

```text
http://127.0.0.1:8080/v1
```

On the target Nano, the systemd example selects the existing advisory-only SYSOP bridge at `http://127.0.0.1:8790`. The native adapter maps Generator calls to `agency_ai_engineer` and Critic/repair calls to `agency_code_reviewer`; it does not bypass the bridge with caller-supplied system messages.

## Hardware safety model

Jetson Orin CPU and GPU share LPDDR memory. ConglomerAIte therefore treats `tegrastats` RAM, Linux `MemAvailable`, and cgroup headroom as unified-memory safety signals; optional NVML support is best effort and is not described as discrete VRAM on Jetson. The application checks pressure around each model call while the tegrastats sampler runs continuously. Systemd `MemoryHigh`/`MemoryMax`, limited local concurrency/context, and the existing SRE runbook remain the final containment layer.

Tune every threshold with target-device measurements. NVMe swap can soften a transient allocation failure, but it is not extra GPU memory and sustained swap activity is a failure signal.

## Edge deployment

The deployment script stages a release over SSH/rsync, validates and seals it root-owned/read-only on the Nano, atomically changes the `current` symlink, restarts only the allowlisted service when explicitly requested, checks health, and rolls back managed files and the symlink on failure.

```bash
deploy/deploy.sh --dry-run
deploy/deploy.sh --target nano
```

Run it from WSL, Git Bash, Linux, or macOS with `bash`, `rsync`, and `ssh`. It does not copy secrets, virtual environments, model weights, caches, or benchmark artifacts. Installation and tuning are documented in [the service isolation guide](systemd/README.md).

## Validation and evidence

Run the credential-stripped offline validation on Windows, Linux, or the Nano:

```bash
python scripts/validate_offline.py
```

The script removes Qwen/DashScope credentials from its child-process environment,
forces offline configuration, and runs only deterministic tests and compilation.
It never calls QwenCloud or a local model endpoint.

Equivalent individual commands are:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
```

After installing the package, run a real comparison corpus with:

```bash
conglomeraite-benchmark benchmarks/tasks.example.jsonl \
  --config config/conglomeraite.example.json \
  --output artifacts/baseline-vs-swarm.json
```

The harness reports a descriptive one-shot baseline and a stronger single-agent self-refinement baseline bounded by the swarm's observed call, token (when reported), and wall-time budgets. Held-out evaluator calls are labeled and excluded from work cost.

Do not claim a swarm efficiency improvement until it is measured. Use the included benchmark harness with the same corpus, model, and token/wall-clock budget for both the single-agent and swarm modes. Publish raw JSON/CSV, the commands used, p50/p95 latency, token/cost totals, peak memory, quality score, completion rate, and failover recovery—not only a favorable average.

The public source repository is available at [github.com/Destr0yering/conglomeraite](https://github.com/Destr0yering/conglomeraite). The Devpost package still needs real-world evidence that code generation cannot create: an Alibaba Cloud Workbench screenshot, target-device benchmark results, and a public approximately three-minute working demo. The architecture upload is ready as [docs/architecture-diagram.svg](docs/architecture-diagram.svg). The exact shot list is in [the submission checklist](docs/submission-checklist.md), and the three-paragraph copy is in [the Devpost pitch](docs/devpost-pitch.md).

## Repository map

- `src/conglomeraite/` — providers, failover router, strict score parser, refinement loop, telemetry, CLI
- `config/` — secret-free example configuration
- `systemd/` — orchestrator unit, local-model safety drop-in, environment template, install notes
- `deploy/` — staged laptop-to-Jetson deployment
- `cloud/alibaba-telemetry/` — undeployed HMAC-verified Function Compute metadata receiver scaffold
- `tests/` — deterministic parser, routing, memory, loop, and CLI tests
- `docs/` — architecture, model choice, pitch, and submission evidence
- `evidence/` — sanitized live cloud, benchmark, and Nano bridge observations
- `scripts/validate_offline.py` — credential-stripped, zero-inference validation

## License

MIT. See [`LICENSE`](LICENSE).
