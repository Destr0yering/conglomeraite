# MVP results — 2026-07-18

## Live 10/10 convergence

After live testing exposed missing rubric propagation and hidden output truncation, the same QwenCloud task was rerun unchanged. `qwen-plus` scored the first draft 8/10, applied targeted corrections, and reached structurally valid 10/10 consensus on iteration two. The run used four cloud calls, 3,890 input tokens, 1,970 output tokens, and 41.54 seconds wall time. Neither call degraded or hit the output limit. The commit-safe summary is in `evidence/live-cloud-smoke-v3.summary.json`.

## Three-task baseline pilot

All three tasks completed. Against the budget-matched single-agent self-refiner, the swarm averaged a 0.796 latency ratio and 0.767 output-token ratio—about 20.4% lower latency and 23.3% fewer output tokens. Quality was non-inferior and faster on two of three tasks, but the remaining task regressed by one point; mean quality gain was therefore -0.33 and strict swarm win rate was 0%. Against one-shot generation, mean quality gain was 0.0. This pilot supports a narrower efficiency observation, not a general superiority claim. Evaluation used the same configured Critic and is not independent. Raw sanitized records are in `evidence/baseline-vs-swarm-pilot.json`.

## Nano SYSOP bridge smoke

The existing `sysop-qwen-bridge.service` and `llama.service` were active. A bounded explicit `agency_ai_engineer` request returned `SYSOP_EDGE_OK`; the bridge audit recorded 36.411 seconds, 1,497 input tokens, and a 384-token output cap. The post-call snapshot showed 2,683 MB available RAM, 1,684 MB swap in use, and approximately 2.27 GB charged to `llama.service`. No service was changed or restarted. The metadata-only record is in `evidence/edge-sysop-smoke.summary.json`.

## Claims and blockers

Safe current claims:

- QwenCloud credentials and `qwen-plus` access work through the repository provider.
- The bounded loop has demonstrated a real 8/10 → 10/10 cloud refinement.
- The Nano's existing advisory SYSOP bridge and local Qwen model respond successfully.
- On this three-task laptop pilot, the swarm used fewer output tokens and less wall time on quality-noninferior cases.

Do not yet claim end-to-end edge failover or production OOM containment. The active Nano runtime is `llama.service`, not `llama-safe.service`; it has no cgroup memory ceilings, binds port 8080 to `0.0.0.0`, and its containment firewall unit is failed. Those changes require an explicit maintenance-window deployment decision under the Nano's governance rules. Alibaba Function Compute deployment, Workbench proof, external/blinded evaluation, forced-network-loss footage, and target-device ConglomerAIte execution also remain open.
