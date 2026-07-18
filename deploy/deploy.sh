#!/usr/bin/env bash
# Stage and atomically activate ConglomerAIte on a Jetson edge node.
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"

EDGE_TARGET="${EDGE_TARGET:-nano}"
REMOTE_BASE="/opt/conglomeraite"
RESTART_LLAMA=0
MODEL_PROFILE="${MODEL_PROFILE:-sysop-bridge}"
ALLOW_ACTIVE_TASKS=0
DRY_RUN=0
LLAMA_HEALTH_URL="${LLAMA_HEALTH_URL:-http://127.0.0.1:8080/health}"

SSH_ARGS=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=3
  -o StrictHostKeyChecking=yes
)
RSYNC_RSH="ssh -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=yes"

usage() {
  cat <<'EOF'
Usage: deploy/deploy.sh [options]

Options:
  --target USER@HOST     SSH target or configured host alias (default: $EDGE_TARGET or nano)
  --model-profile NAME   sysop-bridge (default) or llama-safe
  --restart-llama       Restart the allowlisted llama-safe.service after activation
  --allow-active-tasks  Permit an atomic release switch while task instances are active
  --dry-run             Perform local checks and print the plan without remote writes
  -h, --help            Show this help

Environment:
  EDGE_TARGET           Alternative to --target
  MODEL_PROFILE         Alternative to --model-profile
  LLAMA_HEALTH_URL      Health URL checked only with --restart-llama

The remote layout is intentionally fixed at /opt/conglomeraite because the hardened
systemd units use that read-only application path. Accept the host key before using
this non-interactive script; StrictHostKeyChecking is never disabled.
EOF
}

log() {
  printf '[deploy] %s\n' "$*" >&2
}

die() {
  log "ERROR: $*"
  exit 1
}

on_error() {
  local line="$1"
  local status="$2"
  log "FAILED at local line ${line} (exit ${status}). The previous current symlink remains active unless remote activation explicitly reported a rollback."
  exit "$status"
}
trap 'on_error "$LINENO" "$?"' ERR

while (($#)); do
  case "$1" in
    --target)
      (($# >= 2)) || die "--target requires USER@HOST or a host alias"
      EDGE_TARGET="$2"
      shift 2
      ;;
    --restart-llama)
      RESTART_LLAMA=1
      shift
      ;;
    --model-profile)
      (($# >= 2)) || die "--model-profile requires sysop-bridge or llama-safe"
      MODEL_PROFILE="$2"
      shift 2
      ;;
    --allow-active-tasks)
      ALLOW_ACTIVE_TASKS=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

[[ "$EDGE_TARGET" =~ ^([A-Za-z0-9._-]+@)?[A-Za-z0-9._-]+$ ]] \
  || die "unsafe SSH target; use USER@HOST or a configured alias"
[[ "$LLAMA_HEALTH_URL" == http://127.0.0.1:*/* ]] \
  || die "LLAMA_HEALTH_URL must be an HTTP loopback URL with an explicit port"
[[ "$LLAMA_HEALTH_URL" != *[[:space:]]* ]] \
  || die "LLAMA_HEALTH_URL must not contain whitespace"
[[ "$MODEL_PROFILE" == sysop-bridge || "$MODEL_PROFILE" == llama-safe ]] \
  || die "MODEL_PROFILE must be sysop-bridge or llama-safe"
if ((RESTART_LLAMA)) && [[ "$MODEL_PROFILE" != llama-safe ]]; then
  die "--restart-llama is valid only with --model-profile llama-safe"
fi

required_commands=(bash)
if ((DRY_RUN == 0)); then
  required_commands+=(ssh rsync)
fi
for command_name in "${required_commands[@]}"; do
  command -v "$command_name" >/dev/null 2>&1 \
    || die "required command is not installed: ${command_name}"
done

required_files=(
  pyproject.toml
  src/conglomeraite/__init__.py
  systemd/conglomeraite.slice
  systemd/conglomeraite@.service
  systemd/conglomeraite.env.example
  systemd/config.json.example
)
if [[ "$MODEL_PROFILE" == llama-safe ]]; then
  required_files+=(systemd/llama-safe.service.d/20-conglomeraite-resources.conf)
fi
for relative_path in "${required_files[@]}"; do
  [[ -f "${REPO_ROOT}/${relative_path}" ]] \
    || die "required repository file is missing: ${relative_path}"
done

bash -n "${BASH_SOURCE[0]}"
if command -v python3 >/dev/null 2>&1; then
  PYTHONPATH="${REPO_ROOT}/src" python3 -m compileall -q "${REPO_ROOT}/src"
else
  log "WARNING: python3 is unavailable locally; remote Python validation remains mandatory"
fi

if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$REPO_ROOT" diff --check
  revision="$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD 2>/dev/null || printf 'worktree')"
else
  revision="worktree"
fi
deploy_id="$(date -u +%Y%m%dT%H%M%SZ)-${revision}-$$"
remote_release="${REMOTE_BASE}/releases/${deploy_id}"

log "target: ${EDGE_TARGET}"
log "release: ${remote_release}"
log "model profile: ${MODEL_PROFILE}"
log "model restart requested: ${RESTART_LLAMA} (fixed allowlist: llama-safe.service)"

if ((DRY_RUN)); then
  log "DRY RUN: would create a staged release, rsync the filtered tree, validate it remotely, install systemd files, and atomically switch current"
  log "DRY RUN: no network connection or remote write was attempted"
  exit 0
fi

log "checking SSH access and creating an unprivileged upload directory"
ssh "${SSH_ARGS[@]}" "$EDGE_TARGET" \
  bash -s -- "$REMOTE_BASE" "$remote_release" <<'REMOTE_PREP'
set -Eeuo pipefail
base="$1"
release="$2"
[[ "$base" == /opt/conglomeraite ]] || { echo "unexpected remote base" >&2; exit 64; }
[[ "$release" == "$base"/releases/* ]] || { echo "unsafe release path" >&2; exit 64; }
sudo -n true
remote_user="$(id -un)"
remote_group="$(id -gn)"
sudo install -d -m 0755 "$base" "$base/releases"
if sudo test -e "$release"; then
  echo "release path already exists: $release" >&2
  exit 73
fi
sudo install -d -o "$remote_user" -g "$remote_group" -m 0755 "$release"
sudo touch "$base/.deploy.lock"
sudo chown "$remote_user:$remote_group" "$base/.deploy.lock"
sudo chmod 0600 "$base/.deploy.lock"
REMOTE_PREP

log "uploading staged release"
rsync \
  --archive \
  --compress \
  --delay-updates \
  --partial \
  --human-readable \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='venv/' \
  --exclude='__pycache__/' \
  --exclude='.pytest_cache/' \
  --exclude='.mypy_cache/' \
  --exclude='.ruff_cache/' \
  --exclude='.coverage' \
  --exclude='htmlcov/' \
  --exclude='artifacts/' \
  --exclude='models/' \
  --exclude='model-cache/' \
  --exclude='*.gguf' \
  --exclude='*.safetensors' \
  --exclude='*.onnx' \
  --exclude='*.ckpt' \
  --exclude='*.pt' \
  --exclude='*.pth' \
  --exclude='*.bin' \
  --exclude='*.py[co]' \
  --exclude='/config/conglomeraite.json' \
  --exclude='.env' \
  --exclude='.env.*' \
  --exclude='*.key' \
  --exclude='*.pem' \
  --exclude='secrets/' \
  -e "$RSYNC_RSH" \
  "${REPO_ROOT}/" "${EDGE_TARGET}:${remote_release}/"

log "validating and activating release"
ssh "${SSH_ARGS[@]}" "$EDGE_TARGET" \
  bash -s -- \
    "$REMOTE_BASE" \
    "$remote_release" \
    "$MODEL_PROFILE" \
    "$RESTART_LLAMA" \
    "$ALLOW_ACTIVE_TASKS" \
    "$LLAMA_HEALTH_URL" <<'REMOTE_ACTIVATE'
set -Eeuo pipefail
IFS=$'\n\t'

base="$1"
release="$2"
model_profile="$3"
restart_llama="$4"
allow_active="$5"
health_url="$6"
unit_dir=/etc/systemd/system
dropin_dir="$unit_dir/llama-safe.service.d"
managed_paths=(
  "$unit_dir/conglomeraite.slice"
  "$unit_dir/conglomeraite@.service"
  "/etc/conglomeraite/conglomeraite.env"
  "/etc/conglomeraite/config.json"
)
if [[ "$model_profile" == llama-safe ]]; then
  managed_paths+=("$dropin_dir/20-conglomeraite-resources.conf")
fi

[[ "$base" == /opt/conglomeraite ]] || { echo "unexpected remote base" >&2; exit 64; }
[[ "$release" == "$base"/releases/* ]] || { echo "unsafe release path" >&2; exit 64; }
[[ "$restart_llama" =~ ^[01]$ && "$allow_active" =~ ^[01]$ ]] \
  || { echo "invalid deployment flag" >&2; exit 64; }
[[ "$model_profile" == sysop-bridge || "$model_profile" == llama-safe ]] \
  || { echo "invalid model profile" >&2; exit 64; }
if [[ "$restart_llama" == 1 && "$model_profile" != llama-safe ]]; then
  echo "llama restart requires the llama-safe model profile" >&2
  exit 64
fi
sudo -n true
command -v flock >/dev/null 2>&1 \
  || { echo "remote deployment requires util-linux flock" >&2; exit 69; }
exec 9>"$base/.deploy.lock"
flock -n 9 \
  || { echo "another ConglomerAIte deployment holds $base/.deploy.lock" >&2; exit 73; }
if [[ "$restart_llama" == 1 || "$model_profile" == sysop-bridge ]]; then
  command -v curl >/dev/null 2>&1 \
    || { echo "selected model profile requires curl for a health check" >&2; exit 69; }
fi

previous_release="$(readlink -f "$base/current" 2>/dev/null || true)"
backup_dir="$(mktemp -d /tmp/conglomeraite-deploy.XXXXXX)"
absent_manifest="$backup_dir/absent"
touch "$absent_manifest"
managed_mutated=0
symlink_switched=0
restart_attempted=0

rollback() {
  status=$?
  trap - ERR
  set +e
  echo "remote activation failed (exit ${status}); rolling back" >&2

  if ((managed_mutated)); then
    for path in "${managed_paths[@]}"; do
      if grep -Fqx "$path" "$absent_manifest"; then
        sudo rm -f -- "$path"
      else
        sudo install -d -m 0755 "$(dirname -- "$path")"
        sudo cp -a -- "$backup_dir$path" "$path"
      fi
    done
    sudo systemctl daemon-reload
  fi

  if ((symlink_switched)); then
    if [[ -n "$previous_release" ]]; then
      sudo ln -sfn "$previous_release" "$base/current"
    else
      sudo rm -f -- "$base/current"
    fi
  fi

  if ((restart_attempted)); then
    sudo systemctl restart llama-safe.service
  fi
  sudo rm -rf -- "$backup_dir"
  exit "$status"
}
trap rollback ERR

# Validate the staged tree before changing system state.
bash -n "$release/deploy/deploy.sh"
PYTHONPATH="$release/src" /usr/bin/python3 -m compileall -q "$release/src"
PYTHONPATH="$release/src" /usr/bin/python3 -m conglomeraite --help >/dev/null
sudo systemd-analyze verify \
  "$release/systemd/conglomeraite.slice" \
  "$release/systemd/conglomeraite@.service"
if [[ "$model_profile" == sysop-bridge ]]; then
  sudo systemctl cat sysop-qwen-bridge.service >/dev/null
  systemctl is-active --quiet sysop-qwen-bridge.service \
    || { echo "sysop-qwen-bridge.service is not active" >&2; exit 69; }
  curl --fail --silent --show-error --max-time 5 \
    http://127.0.0.1:8790/health | grep -q '"status":"ok"' \
    || { echo "SYSOP Qwen bridge health is not ok" >&2; exit 69; }
else
  sudo systemctl cat llama-safe.service >/dev/null
fi

active_tasks="$(systemctl list-units \
  --type=service \
  --state=activating,active \
  --no-legend \
  'conglomeraite@*.service' 2>/dev/null | awk '{print $1}' || true)"
if [[ -n "$active_tasks" && "$allow_active" != 1 ]]; then
  echo "active ConglomerAIte tasks prevent deployment:" >&2
  printf '%s\n' "$active_tasks" >&2
  echo "wait for completion or pass --allow-active-tasks" >&2
  exit 75
fi

if ! getent passwd conglomeraite >/dev/null; then
  sudo useradd \
    --system \
    --home-dir /var/lib/conglomeraite \
    --shell /usr/sbin/nologin \
    conglomeraite
fi
sudo install -d -o conglomeraite -g conglomeraite -m 0750 \
  /var/lib/conglomeraite \
  /var/lib/conglomeraite/tasks \
  /var/lib/conglomeraite/results \
  /var/lib/conglomeraite/state
sudo install -d -o root -g conglomeraite -m 0750 /etc/conglomeraite

for path in "${managed_paths[@]}"; do
  if sudo test -e "$path"; then
    sudo cp -a --parents "$path" "$backup_dir"
  else
    printf '%s\n' "$path" >>"$absent_manifest"
  fi
done

# From this point every managed-file failure restores every selected managed path.
managed_mutated=1
if ! sudo test -e /etc/conglomeraite/conglomeraite.env; then
  sudo install -o root -g conglomeraite -m 0640 \
    "$release/systemd/conglomeraite.env.example" \
    /etc/conglomeraite/conglomeraite.env
fi
if ! sudo test -e /etc/conglomeraite/config.json; then
  sudo install -o root -g conglomeraite -m 0640 \
    "$release/systemd/config.json.example" \
    /etc/conglomeraite/config.json
fi

sudo install -o root -g root -m 0644 \
  "$release/systemd/conglomeraite.slice" \
  "$unit_dir/conglomeraite.slice"
sudo install -o root -g root -m 0644 \
  "$release/systemd/conglomeraite@.service" \
  "$unit_dir/conglomeraite@.service"
if [[ "$model_profile" == llama-safe ]]; then
  sudo install -d -m 0755 "$dropin_dir"
  sudo install -o root -g root -m 0644 \
    "$release/systemd/llama-safe.service.d/20-conglomeraite-resources.conf" \
    "$dropin_dir/20-conglomeraite-resources.conf"
fi

# The upload owner can no longer alter code after validation. Root retains the
# ability to remove a failed staged release; service users receive read/execute only.
sudo chown -R root:root "$release"
sudo find "$release" -type d -exec chmod 0555 {} +
sudo find "$release" -type f -exec chmod 0444 {} +

pending_link="$base/.current-$(basename -- "$release")"
sudo rm -f -- "$pending_link"
sudo ln -s "$release" "$pending_link"
sudo mv -Tf "$pending_link" "$base/current"
symlink_switched=1

sudo systemctl daemon-reload
sudo systemd-analyze verify \
  "$unit_dir/conglomeraite.slice" \
  "$unit_dir/conglomeraite@.service"
sudo -u conglomeraite env \
  PYTHONPATH="$base/current/src" \
  /usr/bin/python3 -m conglomeraite --help >/dev/null

if [[ "$model_profile" == sysop-bridge ]]; then
  systemctl is-active --quiet sysop-qwen-bridge.service
  curl --fail --silent --show-error --max-time 5 \
    http://127.0.0.1:8790/health | grep -q '"status":"ok"'
elif [[ "$restart_llama" == 1 ]]; then
  restart_attempted=1
  sudo systemctl restart llama-safe.service
  healthy=0
  for _ in $(seq 1 60); do
    if systemctl is-active --quiet llama-safe.service; then
      if curl --fail --silent --show-error --max-time 2 "$health_url" >/dev/null; then
        healthy=1
        break
      fi
    fi
    sleep 1
  done
  if ((healthy == 0)); then
    systemctl status --no-pager llama-safe.service >&2 || true
    journalctl -u llama-safe.service -n 80 --no-pager >&2 || true
    exit 70
  fi
else
  echo "llama-safe.service was not restarted; new cgroup settings apply on its next start" >&2
fi

trap - ERR
sudo rm -rf -- "$backup_dir"
printf '%s\n' "$(basename -- "$release")" | sudo tee "$base/DEPLOYED_RELEASE" >/dev/null
echo "activated $release"
REMOTE_ACTIVATE

trap - ERR
log "SUCCESS: ${remote_release} is active"
if [[ "$MODEL_PROFILE" == llama-safe ]] && ((RESTART_LLAMA == 0)); then
  log "Run again with --restart-llama during a maintenance window to apply the llama-safe drop-in immediately"
fi
