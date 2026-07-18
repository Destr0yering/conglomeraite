#!/usr/bin/env bash
# Root-side, rollback-capable activation for a git-archive release bundle.
set -Eeuo pipefail
IFS=$'\n\t'

usage() {
  echo "usage: sudo bash nano_activate_from_archive.sh ARCHIVE SHA256 RELEASE_ID" >&2
  exit 64
}

[[ $# -eq 3 ]] || usage
archive="$1"
expected_sha="$2"
release_id="$3"
base=/opt/conglomeraite
release="$base/releases/$release_id"
unit_dir=/etc/systemd/system
backup="/var/lib/conglomeraite/deploy-backups/$release_id"
absent_manifest="$backup/absent"
managed_paths=(
  "$unit_dir/conglomeraite.slice"
  "$unit_dir/conglomeraite@.service"
  "$unit_dir/llama.service.d/20-conglomeraite-resources.conf"
  /etc/conglomeraite/conglomeraite.env
  /etc/conglomeraite/config.json
)

[[ ${EUID:-$(id -u)} -eq 0 ]] || {
  echo "activation must run as root" >&2
  exit 77
}
[[ "$archive" == /tmp/conglomeraite-*.tar.gz && -f "$archive" ]] || {
  echo "archive must be an existing /tmp/conglomeraite-*.tar.gz file" >&2
  exit 64
}
[[ "$expected_sha" =~ ^[0-9a-fA-F]{64}$ ]] || {
  echo "invalid SHA-256" >&2
  exit 64
}
[[ "$release_id" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7,40}$ ]] || {
  echo "unsafe release id" >&2
  exit 64
}
[[ "$release" == "$base/releases/"* ]] || {
  echo "unsafe release path" >&2
  exit 64
}

actual_sha="$(sha256sum "$archive" | awk '{print $1}')"
[[ "$actual_sha" == "${expected_sha,,}" ]] || {
  echo "archive SHA-256 mismatch" >&2
  exit 65
}
if tar -tzf "$archive" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
  echo "archive contains an unsafe path" >&2
  exit 65
fi
systemctl is-active --quiet sysop-qwen-bridge.service
curl --fail --silent --show-error --max-time 5 \
  http://127.0.0.1:8790/health | grep -q '"status":"ok"'
active_tasks="$(systemctl list-units --type=service \
  --state=activating,active --no-legend 'conglomeraite@*.service' \
  2>/dev/null | awk '{print $1}' || true)"
[[ -z "$active_tasks" ]] || {
  echo "active ConglomerAIte tasks prevent activation:" >&2
  printf '%s\n' "$active_tasks" >&2
  exit 75
}
[[ ! -e "$release" ]] || {
  echo "release already exists: $release" >&2
  exit 73
}

previous_release="$(readlink -f "$base/current" 2>/dev/null || true)"
symlink_switched=0
managed_mutated=0
model_restart_attempted=0

restore_path() {
  local path="$1"
  if grep -Fqx "$path" "$absent_manifest"; then
    rm -f -- "$path"
  else
    install -d -m 0755 "$(dirname -- "$path")"
    cp -a -- "$backup$path" "$path"
  fi
}

rollback() {
  local status=$?
  trap - ERR
  set +e
  echo "activation failed (exit $status); restoring previous state" >&2
  if ((managed_mutated)); then
    for path in "${managed_paths[@]}"; do
      restore_path "$path"
    done
    systemctl daemon-reload
  fi
  if ((symlink_switched)); then
    if [[ -n "$previous_release" ]]; then
      ln -sfn "$previous_release" "$base/current"
    else
      rm -f -- "$base/current"
    fi
  fi
  if ((model_restart_attempted)); then
    systemctl restart llama.service
  fi
  exit "$status"
}
trap rollback ERR

install -d -m 0755 "$base" "$base/releases"
install -d -m 0700 "$backup"
: >"$absent_manifest"
install -d -m 0755 "$release"
tar -xzf "$archive" -C "$release"

required_files=(
  pyproject.toml
  src/conglomeraite/__init__.py
  deploy/nano_outage_demo.sh
  systemd/conglomeraite.slice
  systemd/conglomeraite@.service
  systemd/conglomeraite.env.example
  systemd/config.json.example
  systemd/llama.service.d/20-conglomeraite-resources.conf
)
for relative_path in "${required_files[@]}"; do
  [[ -f "$release/$relative_path" ]] || {
    echo "missing release file: $relative_path" >&2
    exit 65
  }
done
bash -n "$release/deploy/deploy.sh"
bash -n "$release/deploy/nano_activate_from_archive.sh"
bash -n "$release/deploy/nano_outage_demo.sh"
PYTHONPATH="$release/src" /usr/bin/python3 -m compileall -q "$release/src"
PYTHONPATH="$release/src" /usr/bin/python3 -m conglomeraite --help >/dev/null

if ! getent passwd conglomeraite >/dev/null; then
  useradd --system --home-dir /var/lib/conglomeraite \
    --shell /usr/sbin/nologin conglomeraite
fi
install -d -o conglomeraite -g conglomeraite -m 0750 \
  /var/lib/conglomeraite \
  /var/lib/conglomeraite/tasks \
  /var/lib/conglomeraite/results \
  /var/lib/conglomeraite/state
install -d -o root -g conglomeraite -m 0750 /etc/conglomeraite

for path in "${managed_paths[@]}"; do
  if [[ -e "$path" ]]; then
    install -d -m 0700 "$backup$(dirname -- "$path")"
    cp -a -- "$path" "$backup$path"
  else
    printf '%s\n' "$path" >>"$absent_manifest"
  fi
done

managed_mutated=1
if [[ ! -e /etc/conglomeraite/conglomeraite.env ]]; then
  install -o root -g conglomeraite -m 0640 \
    "$release/systemd/conglomeraite.env.example" \
    /etc/conglomeraite/conglomeraite.env
fi
if [[ ! -e /etc/conglomeraite/config.json ]]; then
  install -o root -g conglomeraite -m 0640 \
    "$release/systemd/config.json.example" \
    /etc/conglomeraite/config.json
fi
install -o root -g root -m 0644 \
  "$release/systemd/conglomeraite.slice" \
  "$unit_dir/conglomeraite.slice"
install -o root -g root -m 0644 \
  "$release/systemd/conglomeraite@.service" \
  "$unit_dir/conglomeraite@.service"
install -d -m 0755 "$unit_dir/llama.service.d"
install -o root -g root -m 0644 \
  "$release/systemd/llama.service.d/20-conglomeraite-resources.conf" \
  "$unit_dir/llama.service.d/20-conglomeraite-resources.conf"

chown -R root:root "$release"
find "$release" -type d -exec chmod 0555 {} +
find "$release" -type f -exec chmod 0444 {} +
pending_link="$base/.current-$release_id"
rm -f -- "$pending_link"
ln -s "$release" "$pending_link"
mv -Tf "$pending_link" "$base/current"
symlink_switched=1

systemctl daemon-reload
systemd-analyze verify \
  "$unit_dir/conglomeraite.slice" \
  "$unit_dir/conglomeraite@.service" \
  "$unit_dir/llama.service"
sudo -u conglomeraite env PYTHONPATH="$base/current/src" \
  /usr/bin/python3 -m conglomeraite --help >/dev/null

model_restart_attempted=1
systemctl restart llama.service
healthy=0
for _ in $(seq 1 60); do
  if systemctl is-active --quiet llama.service && \
     curl --fail --silent --show-error --max-time 2 \
       http://127.0.0.1:8080/health >/dev/null; then
    healthy=1
    break
  fi
  sleep 1
done
[[ "$healthy" -eq 1 ]] || {
  systemctl status --no-pager llama.service >&2 || true
  journalctl -u llama.service -n 80 --no-pager >&2 || true
  exit 70
}
systemctl is-active --quiet sysop-qwen-bridge.service
curl --fail --silent --show-error --max-time 5 \
  http://127.0.0.1:8790/health | grep -q '"status":"ok"'
ss -ltn | grep -Eq '127\.0\.0\.1:8080[[:space:]]'
if ss -ltn | grep -Eq '0\.0\.0\.0:8080[[:space:]]'; then
  echo "llama port remains publicly bound" >&2
  exit 70
fi

trap - ERR
printf '%s\n' "$release_id" >"$base/DEPLOYED_RELEASE"
echo "activated $release"
systemctl show llama.service \
  -p ActiveState -p SubState -p Slice -p MemoryCurrent -p MemoryPeak \
  -p MemoryHigh -p MemoryMax -p MemorySwapMax -p OOMScoreAdjust \
  -p OOMPolicy -p Result -p NRestarts
