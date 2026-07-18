# Devpost executive summary

**ConglomerAIte™ turns a fragile cloud agent into a fault-tolerant swarm that keeps thinking at the edge.** Built for QwenCloud Track 5 (EdgeAgent) with Track 3 (Agent Society) mechanics, its reference CLI accepts SYSOP-style tasks and includes a native adapter for the Nano's advisory-only SYSOP Qwen Bridge. Generator and Critic calls use QwenCloud while connectivity is healthy, then map to the bridge's AI Engineer and Code Reviewer roles on retryable failure. Offline mode keeps task inference local, while metadata-only traces make route changes inspectable without putting task or draft text in journald.

**Its signature capability is an autonomous, bounded 10/10 refinement contract.** A Generator proposes a solution; an independent Critic returns a machine-parseable score plus targeted corrections; and ConglomerAIte™ revises until a structurally valid 10/10 has no declared blockers or a time, iteration, stagnation, provider, or RAM boundary ends the run. The guard samples Jetson unified-memory pressure through tegrastats/proc/cgroup sources, with optional NVML elsewhere, and refuses to schedule another call once sampled pressure is already unsafe. It is containment, not a promise to prevent a sudden CUDA/driver OOM inside a running model call.

**This is agentic IoT instrumented for the failure modes of the real world.** Systemd cgroups place separate limits around the orchestrator and local inference server; bounded retry/cooldown logic limits retry storms; and the staged SSH deployment can roll back managed units and releases. The included benchmark harness enables a fair single-agent comparison, but efficiency remains a measurement to prove on the actual Nano. An HMAC-protected Alibaba Function Compute telemetry receiver is included as an undeployed scaffold; judges should treat real Alibaba invocation logs, screenshots, network-drop footage, and target-device benchmark artifacts—not source code alone—as the proof.

## Suggested tagline

Fault-tolerant Qwen swarm intelligence that self-corrects to 10/10—and keeps working when the cloud disappears.
