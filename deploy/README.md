# Laptop-to-Jetson deployment

Run the script from Git Bash, WSL, Linux, or macOS with `ssh` and `rsync` available. The `nano` SSH alias is the default; strict host-key verification and non-interactive public-key/sudo access are required.

```bash
# Inspect local validation and the deployment plan; makes no network connection.
./deploy/deploy.sh --dry-run

# Stage, validate, and atomically activate code and systemd files.
./deploy/deploy.sh --target destro@jetson-hostname --model-profile sysop-bridge

# During a maintenance window, also restart and health-check the local model.
./deploy/deploy.sh --target nano --model-profile llama-safe --restart-llama
```

The script uploads to a unique `/opt/conglomeraite/releases/<timestamp>-<revision>-<pid>` directory, takes a remote `flock` for activation, validates the code/CLI/units, and seals the release root-owned with read-only service access before switching `/opt/conglomeraite/current`. It refuses to switch while a `conglomeraite@*.service` task is active unless `--allow-active-tasks` is explicit. All managed unit/config files and the previous symlink are restored if any later mutation, smoke check, or requested model restart fails.

The default `sysop-bridge` profile requires the existing bridge to be active and healthy, does not install a model-service drop-in, and never restarts the model. The optional `llama-safe` profile installs the supplied drop-in; only that profile accepts `--restart-llama`. Loading model weights is disruptive and belongs in the Nano maintenance window. The orchestrator is a one-shot template unit, so there is no idle daemon to restart; its next systemd task instance uses the new `current` release.

**Observed-target warning:** the current Nano runs `llama.service` behind `sysop-qwen-bridge.service`, not `llama-safe.service`. Use only the `sysop-bridge` profile unless an operator explicitly approves a service migration. Never use `--restart-llama` on the observed target in its current state.

Repository `.env` files, `config/conglomeraite.json`, keys, certificates, caches, benchmark artifacts, secrets directories, and common model weights (`*.gguf`, `*.safetensors`, `*.onnx`, `*.ckpt`, `*.pt`, `*.pth`, `*.bin`, `models/`) are excluded. The script never downloads a model and never overwrites existing `/etc/conglomeraite/config.json` or `conglomeraite.env`; first deployment installs secret-free examples only. Edit the environment file on the Nano and keep it root-managed.

Useful overrides:

```bash
EDGE_TARGET=nano LLAMA_HEALTH_URL=http://127.0.0.1:8080/health \
  ./deploy/deploy.sh --restart-llama
```

On failure, read the exact local line and remote rollback message. If a requested model restart cannot become healthy, the script prints the last 80 journal lines, restores the prior drop-in/release, reloads systemd, and attempts to restart the previous service configuration.
