#!/usr/bin/env bash
# Controlled, zero-paid-API cloud-loss demonstration for the Jetson Nano.
set -Eeuo pipefail
IFS=$'\n\t'

[[ ${EUID:-$(id -u)} -eq 0 ]] || {
  echo "outage demonstration must run as root" >&2
  exit 77
}

task_id=outage-demo
unit="conglomeraite@${task_id}.service"
config=/etc/conglomeraite/config.json
environment=/etc/conglomeraite/conglomeraite.env
task=/var/lib/conglomeraite/tasks/${task_id}.json
trace=/var/lib/conglomeraite/state/${task_id}.trace.json
result=/var/lib/conglomeraite/results/${task_id}.json
evidence=/var/lib/conglomeraite/state/${task_id}-evidence.json
work="$(mktemp -d /tmp/conglomeraite-outage-demo.XXXXXX)"
config_backup="$work/config.json"
environment_backup="$work/conglomeraite.env"
restored=0
backed_up=0

restore() {
  local status=$?
  trap - EXIT ERR INT TERM
  if [[ "$backed_up" -eq 1 && "$restored" -eq 0 ]]; then
    install -o root -g conglomeraite -m 0640 "$config_backup" "$config"
    install -o root -g conglomeraite -m 0640 "$environment_backup" "$environment"
    restored=1
  fi
  rm -rf -- "$work"
  exit "$status"
}
trap restore EXIT ERR INT TERM

systemctl is-active --quiet llama.service
systemctl is-active --quiet sysop-qwen-bridge.service
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8080/health >/dev/null
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8790/health \
  | grep -q '"status":"ok"'
if systemctl is-active --quiet "$unit"; then
  echo "$unit is already active" >&2
  exit 75
fi

cp -a -- "$config" "$config_backup"
cp -a -- "$environment" "$environment_backup"
backed_up=1

# The primary endpoint is loopback port 1, which is closed on the Nano. A fake
# key constructs the cloud provider, but no packet can leave the device and no
# paid QwenCloud request can occur. The real environment is restored on every exit.
python3 - "$config_backup" "$work/config.json" <<'PY'
import json
import sys

source, destination = sys.argv[1:]
with open(source, encoding="utf-8") as handle:
    config = json.load(handle)
config["qwen"].update(
    endpoint="http://127.0.0.1:1/v1",
    model="forced-network-loss-no-external-call",
    timeout_s=2.0,
    max_tokens=256,
)
config["local"].update(
    kind="sysop_bridge",
    endpoint="http://127.0.0.1:8790",
    model="sysop-agents",
    timeout_s=90.0,
    max_tokens=512,
)
config["loop"].update(max_iterations=2, max_elapsed_s=150.0)
config["memory"].update(
    max_used_fraction=0.88,
    min_available_mb=768.0,
    max_gpu_used_fraction=0.92,
    monitor_required=True,
)
config.update(
    cloud_failure_threshold=1,
    cloud_cooldown_s=300.0,
    cloud_retries=0,
    fallback_retries=0,
    offline=False,
)
with open(destination, "w", encoding="utf-8") as handle:
    json.dump(config, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

cat >"$work/conglomeraite.env" <<'EOF'
# Deliberately fake and loopback-only: this demo cannot reach QwenCloud.
QWEN_API_KEY=outage-demo-not-a-real-key
CONGLOMERAITE_QWEN_ENDPOINT=http://127.0.0.1:1/v1
CONGLOMERAITE_QWEN_MODEL=forced-network-loss-no-external-call
CONGLOMERAITE_LOCAL_KIND=sysop_bridge
CONGLOMERAITE_LOCAL_ENDPOINT=http://127.0.0.1:8790
CONGLOMERAITE_LOCAL_MODEL=sysop-agents
CONGLOMERAITE_OFFLINE=false
CONGLOMERAITE_PYTHON=/usr/bin/python3
CONGLOMERAITE_CONFIG=/etc/conglomeraite/config.json
EOF

cat >"$work/task.json" <<'EOF'
{
  "task": "Create a concise five-step continuity plan for an edge IoT gateway that loses cloud connectivity. The plan must keep control local, preserve evidence, bound resource use, and define safe recovery. End with the exact line: EDGE CONTINUITY CONFIRMED",
  "rubric": "Award 10/10 only when the answer has exactly five numbered steps, explicitly identifies local fallback, contains a hardware-safe circuit breaker, preserves a privacy-safe audit trace, defines cloud recovery validation, and ends with EDGE CONTINUITY CONFIRMED. Otherwise return targeted refinements.",
  "cloud_allowed": true
}
EOF

install -o root -g conglomeraite -m 0640 "$work/config.json" "$config"
install -o root -g conglomeraite -m 0640 "$work/conglomeraite.env" "$environment"
install -o conglomeraite -g conglomeraite -m 0640 "$work/task.json" "$task"
rm -f -- "$trace" "$result" "$evidence"

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
tegrastats_before="$(timeout 3 tegrastats --interval 500 2>/dev/null | head -n 1 || true)"
if systemctl start "$unit"; then
  service_start_rc=0
else
  # A bounded provider/deadline stop is valid demo evidence. Capture the
  # unit's non-zero result without triggering this script's ERR rollback trap.
  service_start_rc=$?
fi
tegrastats_after="$(timeout 3 tegrastats --interval 500 2>/dev/null | head -n 1 || true)"
completed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
unit_result="$(systemctl show "$unit" -p Result --value 2>/dev/null || true)"
unit_exec_status="$(systemctl show "$unit" -p ExecMainStatus --value 2>/dev/null || true)"

[[ -f "$trace" ]] || {
  systemctl status --no-pager "$unit" >&2 || true
  journalctl -u "$unit" -n 80 --no-pager >&2 || true
  echo "privacy-safe trace was not produced" >&2
  exit 70
}

release_id="$(cat /opt/conglomeraite/DEPLOYED_RELEASE)"
llama_show="$(systemctl show llama.service \
  -p ActiveState -p SubState -p Slice -p MemoryHigh -p MemoryMax \
  -p MemorySwapMax -p OOMScoreAdjust -p OOMPolicy -p Result)"
listen_local=false
if ss -ltn | grep -Eq '127\.0\.0\.1:8080[[:space:]]' && \
   ! ss -ltn | grep -Eq '0\.0\.0\.0:8080[[:space:]]'; then
  listen_local=true
fi

python3 - \
  "$trace" \
  "$evidence" \
  "$started_at" \
  "$completed_at" \
  "$release_id" \
  "$service_start_rc" \
  "$unit_result" \
  "$unit_exec_status" \
  "$listen_local" \
  "$llama_show" \
  "$tegrastats_before" \
  "$tegrastats_after" <<'PY'
import json
import sys

(
    trace_path,
    evidence_path,
    started_at,
    completed_at,
    release_id,
    service_start_rc,
    unit_result,
    unit_exec_status,
    listen_local,
    llama_show,
    tegrastats_before,
    tegrastats_after,
) = sys.argv[1:]
with open(trace_path, encoding="utf-8") as handle:
    trace = json.load(handle)
calls = trace.get("calls", [])
evidence = {
    "schema_version": "1.0",
    "demo": "forced-cloud-network-loss",
    "started_at": started_at,
    "completed_at": completed_at,
    "release_id": release_id,
    "paid_qwen_api_calls": 0,
    "cloud_failure_injection": "Qwen-compatible endpoint forced to closed loopback 127.0.0.1:1",
    "external_cloud_packets_possible": False,
    "service_start_rc": int(service_start_rc),
    "unit_result": unit_result,
    "unit_exec_status": unit_exec_status,
    "workflow": {
        "status": trace.get("status"),
        "stop_reason": trace.get("stop_reason"),
        "final_score": trace.get("final_score"),
        "best_iteration": trace.get("best_iteration"),
        "metrics": trace.get("metrics", {}),
    },
    "routing": [
        {
            "iteration": call.get("iteration"),
            "role": call.get("role"),
            "selected_provider": call.get("provider"),
            "providers_attempted": call.get("providers_attempted", []),
            "degraded": call.get("degraded"),
            "failover_reason": call.get("failover_reason"),
        }
        for call in calls
    ],
    "nano_safety": {
        "llama_bound_to_loopback_only": listen_local == "true",
        "llama_systemd": llama_show.splitlines(),
        "tegrastats_before": tegrastats_before,
        "tegrastats_after": tegrastats_after,
    },
    "privacy": {
        "task_text_in_evidence": False,
        "draft_text_in_evidence": False,
        "trace_source": "include_text=false",
    },
}
with open(evidence_path, "w", encoding="utf-8") as handle:
    json.dump(evidence, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
chown root:root "$evidence"
chmod 0644 "$evidence"

install -o root -g conglomeraite -m 0640 "$config_backup" "$config"
install -o root -g conglomeraite -m 0640 "$environment_backup" "$environment"
restored=1
trap - EXIT ERR INT TERM
rm -rf -- "$work"

cat "$evidence"
