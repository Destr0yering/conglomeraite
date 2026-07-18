# Jetson service isolation

These files add a bounded ConglomerAIte task unit and an optional resource-control drop-in for installations that actually use `llama-safe.service`. The task unit depends softly on `sysop-qwen-bridge.service`, matching the observed MVP Nano. The deployment does not replace a model `ExecStart` or download model files.

## Observed Nano profile

The 2026-07-18 read-only preflight found `sysop-qwen-bridge.service` and `llama.service` active, while `llama-safe.service` was inactive. The active `llama.service` has no `MemoryHigh`, `MemoryMax`, `MemorySwapMax`, or `OOMScoreAdjust` controls and binds port 8080 to `0.0.0.0`; `nano-8080-firewall.service` was failed. Do not install the `llama-safe.service.d` drop-in or use `--restart-llama` as though it protected the active model. Resolve the active-service identity, port containment, and resource limits in an explicitly approved maintenance window.

## Install and tune

`deploy/deploy.sh` installs the files and creates `/etc/conglomeraite/` on the Nano. Edit the root-managed environment file to add `QWEN_API_KEY`; the JSON config intentionally contains no secret. Validate the effective values after installation:

```bash
sudo systemd-analyze verify \
  /etc/systemd/system/conglomeraite.slice \
  /etc/systemd/system/conglomeraite@.service
sudo systemctl daemon-reload
systemctl cat llama-safe.service
systemctl show llama-safe.service \
  -p Slice -p MemoryHigh -p MemoryMax -p MemorySwapMax -p OOMScoreAdjust
```

Start with the shipped limits, run the worst measured prompt/context repeatedly, and inspect `tegrastats`, `systemd-cgtop`, and:

```bash
systemctl show llama-safe.service \
  -p MemoryCurrent -p MemoryPeak -p MemorySwapCurrent -p Result -p NRestarts
cat /sys/fs/cgroup/conglomeraite.slice/llama-safe.service/memory.events
```

Keep at least 1.5–2 GB of **observed** system headroom at the worst-case p95. Lower model context/batch/output settings before raising `MemoryMax`. `MemoryHigh` should remain below `MemoryMax`, and the slice ceiling must cover both child services without consuming the Nano's entire unified DRAM.

`MemoryMax` is a userspace/cgroup limit, not a CUDA VRAM reservation. Jetson CPU and GPU share DRAM, and some driver/carveout use may not appear as an independently controllable cgroup charge. The in-process tegrastats/proc/cgroup circuit breaker is therefore required. NVMe swap is recovery headroom for pageable CPU memory, not a license to overcommit model weights or KV cache.

## Run a task

Use only filesystem-safe task IDs (`A-Z`, `a-z`, `0-9`, `.`, `_`, `-`) because the ID becomes a systemd instance and filename.

```bash
sudo install -o conglomeraite -g conglomeraite -m 0640 task-42.json \
  /var/lib/conglomeraite/tasks/task-42.json
sudo systemctl start conglomeraite@task-42.service
sudo journalctl -u conglomeraite@task-42.service -f
sudo cat /var/lib/conglomeraite/results/task-42.json
```

The journal receives one metadata-only summary from `--journal-summary`; task,
draft, critique, and final response text are written atomically to the mode-0600
result file instead. Treat both task and result directories as sensitive state.

If `llama-safe.service` hits a memory path accounted to its cgroup, `OOMScoreAdjust=500` and `OOMPolicy=stop` bias containment toward the model while the smaller orchestrator is more likely—but not guaranteed—to record a controlled failure. `StartLimitBurst=3` bounds rapid restart attempts within the configured interval. Investigate and reduce model/context pressure before resetting the failure counter:

```bash
sudo systemctl reset-failed llama-safe.service
sudo systemctl start llama-safe.service
```
