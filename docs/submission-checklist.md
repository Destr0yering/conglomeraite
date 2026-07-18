# QwenCloud Devpost submission checklist

Audited against the live Devpost account and submission fields on **2026-07-18**. Submission closes **2026-07-20 at 2:00 PM Pacific / 5:00 PM Eastern (21:00 UTC)**. The account is registered and a ConglomerAIte project draft now exists, but it has not been submitted to the hackathon.

## Safety freeze

- [x] Stop paid QwenCloud/API testing while the $40 voucher and Free Tier are absent.
- [x] Add `python scripts/validate_offline.py`, which strips Qwen/DashScope keys from child processes and runs only deterministic local tests.
- [ ] Do not resume paid inference unless the user explicitly reverses this instruction.

## Completed implementation and evidence

- [x] Bounded Generator/Critic loop with strict 10/10 JSON consensus checks.
- [x] Parse textual scores such as `8/10` without allowing a text-only 10 to terminate the loop.
- [x] Preserve the best candidate and stop on time, iteration, stagnation, provider, or sampled-memory boundaries.
- [x] QwenCloud primary provider and three-state cloud-to-local failover router.
- [x] Native adapter for the Jetson's advisory-only SYSOP Qwen Bridge.
- [x] tegrastats, `/proc/meminfo`, cgroup, and optional NVML memory observations.
- [x] Systemd slice/task unit and optional `llama-safe.service` resource drop-in.
- [x] Staged SSH/rsync deployment with validation, atomic activation, and rollback.
- [x] HMAC-verified Alibaba Function Compute metadata-only receiver scaffold.
- [x] QwenCloud base URL is visible in `src/conglomeraite/config.py`.
- [x] MIT `LICENSE` exists at the repository root.
- [x] Architecture blueprint and upload-ready `docs/architecture-diagram.svg` exist.
- [x] Three-paragraph pitch and full submission draft exist.
- [x] Devpost project draft created at `https://devpost.com/software/the-conglomeraite`.
- [x] Branded square thumbnail generated, saved under `docs/assets/`, and uploaded to the Devpost draft.
- [x] OBS Studio is installed on the laptop for recording the final under-three-minute demo.
- [x] One real QwenCloud run demonstrated 8/10 to structurally valid 10/10 convergence.
- [x] Three-task baseline pilot is preserved with honest claim limits.
- [x] One real Nano SYSOP-bridge smoke test and memory snapshot are preserved.
- [x] Offline verification passes: 47 core tests, 3 telemetry tests, and Python compilation.
- [x] `deploy/deploy.sh` passes Bash syntax validation with Git for Windows.
- [x] Repository scan found no `sk-ws-` credential in tracked workspace files.
- [x] Initial local Git commits created on `codex/hackathon-mvp`; the working tree was clean after the commits.

## Critical blockers before submission

- [x] **Create the public repository.** `https://github.com/Destr0yering/conglomeraite` is attached as `origin`.
- [ ] **Install/provide `rsync` for deployment.** Git Bash is present, but its current installation does not include `rsync`; the staged deploy script cannot run from this laptop yet.
- [x] **Create the Devpost project.** Draft project `the-conglomeraite` exists; it is not yet a hackathon submission.
- [ ] **Deploy on Alibaba Cloud.** `cloud/alibaba-telemetry/` is tested source only; it is not deployed.
- [ ] **Sign in to Alibaba Cloud in the in-app Browser.** The console is open as a handoff tab, but the browser session is currently signed out.
- [ ] **Capture Workbench proof.** Save a judge-safe screenshot showing the running Alibaba resource and successful invocation/log.
- [ ] **Complete a controlled Jetson deployment.** Direct SYSOP dispatch and the ConglomerAIte systemd task have not run end-to-end on the Nano.
- [ ] **Resolve model-service containment.** The Nano currently runs unrestricted `llama.service`, not the protected `llama-safe.service`; port 8080 exposure/firewall state also needs an approved maintenance decision.
- [ ] **Demonstrate edge degradation.** Cloud and local paths were tested separately, but a single task has not yet continued through a forced network loss on the Nano.
- [ ] **Record and publish the demo.** Use public YouTube or Vimeo and keep the video under three minutes.
- [ ] **Upload the architecture SVG** to the submission form.
- [ ] **Fill every required field and submit** before the deadline; do not wait until the final hour.

## Live Devpost field checklist

- [x] Project name, tagline, description, and Built With list are populated in the Devpost draft.
- [ ] Submitter type: Individual, Team, or Organization — user decision required.
- [ ] Organization name — optional if not applicable.
- [ ] Country of residence for every member — user input required.
- [ ] New versus existing project — user decision required.
- [ ] Project start date in MM-DD-YY — user input required.
- [ ] If the project predates 2026-05-26, describe significant work completed during the submission period.
- [ ] Select **Track 5: EdgeAgent**. Explain the Track 3 Agent Society mechanics in the description; the form accepts one track.
- [x] Public open-source repository URL: `https://github.com/Destr0yering/conglomeraite`.
- [x] Direct URL to `src/conglomeraite/config.py` showing the QwenCloud base URL.
- [ ] Architecture diagram file.
- [ ] Alibaba Cloud Workbench screenshot.
- [ ] Public demo video URL. A website and ZIP file are not required by the current form.
- [ ] AI-tools disclosure — draft ready.
- [ ] Learning level — user selection required.
- [ ] Age-of-majority confirmation — user confirmation required.
- [ ] Eligible-jurisdiction confirmation — user confirmation required.
- [ ] Sponsor/affiliate/government employee confirmation — user confirmation required.
- [ ] Testing instructions — draft ready; add exact edge/test-build access after deployment.
- [ ] Optional public blog/social post URL for the separate blog bonus prize.

## Evidence still needed for competitive claims

- [ ] Target-device ConglomerAIte trace, not only a direct bridge smoke test.
- [ ] Forced network-loss route transition with retained task state and `degraded=true`.
- [ ] Pre/post memory samples, `memory.events`, swap use, and service journal during the edge run.
- [ ] Proof that the actual active model service has measured cgroup limits and adequate headroom, or an explicit disclosure that it does not.
- [ ] Alibaba Function Compute resource view and a successful signed metadata-only invocation.
- [ ] Independent or blinded quality evaluation if claiming quality improvement.
- [ ] More representative tasks if claiming general efficiency; the current three-task pilot supports only a narrow observation.
- [ ] Exact model artifact, quantization, llama.cpp build, JetPack version, context, power mode, and network condition for reproduced edge numbers.

## Recommended execution order

1. Decide the Nano maintenance window and whether to keep `llama.service` with new limits or migrate deliberately to `llama-safe.service`; never run both.
2. Deploy the application with the `sysop-bridge` profile and capture a local-only, zero-paid-inference task trace after explicit approval.
3. Deploy the metadata receiver to Alibaba Function Compute, invoke it with a signed metadata-only event, and capture Workbench/log proof.
4. Record the under-three-minute demo using the existing shot plan: topology, 10/10 evidence, edge/offline continuation, memory containment, measured pilot, and Alibaba proof.
5. Verify the public GitHub repository's MIT license/About section and test every public link in a private/incognito window.
6. Finish the existing Devpost draft: upload the diagram/screenshot, add the video, and complete the user-only eligibility fields.
7. Submit early, reopen the public entry, verify the video/repository/files render without login, and retain a screenshot of the submitted state.

## Three-minute demo shot plan

1. **0:00–0:25 — Problem and topology:** Jetson, SYSOP task boundary, and architecture.
2. **0:25–1:05 — Autonomous refinement:** show the preserved real 8/10 to 10/10 trace and its bounded stop contract; do not trigger new paid inference.
3. **1:05–1:45 — Edge/offline behavior:** show an approved local-only task or pre-recorded forced-loss run, route/degraded flags, and retained state.
4. **1:45–2:15 — Hardware safety:** show memory samples, cgroup settings, and a safe guard trip/replay without inducing an OOM.
5. **2:15–2:40 — Measurements:** show the three-task pilot with its limitations, not a universal superiority claim.
6. **2:40–2:55 — Alibaba proof:** Workbench resource, successful invocation log, and source link with the QwenCloud base URL.
7. **2:55–3:00 — Close:** ConglomerAIte tagline and Track 5 selection.

## Final claims guardrail

Do not claim production OOM prevention, completed end-to-end failover, Alibaba deployment, or general multi-agent superiority until the corresponding evidence above exists. Report task count, models, quantization, context, network condition, power mode, measurement definition, and evaluator independence beside every quantitative claim.
