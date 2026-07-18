# Nano deployment readiness

## Read-only preflight result

The target is reachable and the advisory edge path works, but deployment is intentionally blocked pending a maintenance decision.

Observed on 2026-07-18:

- `sysop-qwen-bridge.service`: active, hardened, advisory-only, `127.0.0.1:8790` plus authenticated Docker gateway;
- `llama.service`: active with one `qwen.gguf` slot, 2,048-token context, approximately 2.27 GB cgroup memory after the smoke run;
- `llama-safe.service`: inactive and disabled;
- available RAM after the smoke run: 2,683 MB; swap used: 1,684 MB;
- `llama.service` resource controls: all unlimited, `OOMScoreAdjust=0`;
- `llama.service` binds `0.0.0.0:8080` and `nano-8080-firewall.service` is failed.

The SYSOP governance file forbids service edits, restarts, deployment, firewall changes, and model-runtime changes without explicit instruction. No remote file or service was changed during this preflight.

## Required maintenance-window decisions

1. Keep the existing `llama.service` + SYSOP bridge profile, or deliberately migrate to `llama-safe.service`. Do not run both.
2. Bind direct llama.cpp access to loopback or restore verified firewall containment before demoing on an untrusted network.
3. Benchmark and then apply cgroup limits to the service that actually owns the model; the shipped `llama-safe` drop-in does not constrain `llama.service`.
4. Use the deploy script's default `sysop-bridge` profile so application activation does not install or restart a model service; reserve `llama-safe` for an explicitly approved migration.
5. Install the QwenCloud credential as a root-managed Nano environment secret; never copy it through the repository or deployment release.
6. Run the forced-network-loss test only after application deployment, with the model and bridge already healthy and a rollback operator present.

## Proposed first controlled edge run

After approval and deployment:

1. Record `free -m`, one tegrastats sample, service states, cgroup limits, and the bridge `/health` response.
2. Submit one cloud-enabled task and confirm a QwenCloud Generator call.
3. Block only the cloud route using an approved reversible method; do not stop the local bridge or model.
4. Confirm the next logical call routes to `sysop-bridge`, retains the task candidate, and records `degraded=true`.
5. Restore connectivity, allow one half-open probe, and verify breaker recovery.
6. Archive metadata-only traces, service journals, `memory.events`, and the exact commands used.
