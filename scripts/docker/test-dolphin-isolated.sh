#!/bin/sh
set -eu

compose="docker compose -f compose.test.yaml"
cleanup() {
  $compose down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

cli() {
  $compose exec --no-TTY dolphin-server /usr/local/bin/dolphin --session docker-proof "$@"
}

wait_for_fake_agent() {
  python3 - $compose exec --no-TTY dolphin-server /usr/local/bin/dolphin --session docker-proof <<'PY'
import json
import subprocess
import sys
import time

deadline = time.monotonic() + 5.0
process_info = ""
ready = False
while (remaining := deadline - time.monotonic()) > 0:
    try:
        process_info = subprocess.check_output(
            [*sys.argv[1:], "pane", "process-info", "--pane", "w1:p1"],
            text=True,
            timeout=remaining,
        )
    except subprocess.TimeoutExpired:
        break
    processes = json.loads(process_info)["result"]["process_info"]["foreground_processes"]
    ready = any(process["argv"] == ["python3", "/usr/local/bin/fake-agent.py"] for process in processes)
    if ready:
        break
    time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))

assert ready, f"fake agent did not become the pane foreground process within 5 seconds: {process_info}"
PY
}

wait_for_board_pane() {
  python3 - $compose exec --no-TTY dolphin-server /usr/local/bin/dolphin --session docker-proof "$board_pane" <<'PY'
import json
import subprocess
import sys
import time

command = sys.argv[1:-1]
pane_id = sys.argv[-1]
deadline = time.monotonic() + 5.0
process_info = ""
ready = False
while (remaining := deadline - time.monotonic()) > 0:
    try:
        process_info = subprocess.check_output(
            [*command, "pane", "process-info", "--pane", pane_id],
            text=True,
            timeout=remaining,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        break
    processes = json.loads(process_info)["result"]["process_info"]["foreground_processes"]
    ready = any(process["argv"] == ["python3", "board.py"] for process in processes)
    if ready:
        break
    time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))

assert ready, f"Workboard did not become the pane foreground process within 5 seconds: {process_info}"
PY
}

$compose build --quiet
$compose up --detach --wait dolphin-server
ready=0
for _ in $(seq 1 300); do
  if cli status server | python3 -c 'import sys; raise SystemExit(0 if "status: running" in sys.stdin.read() else 1)'; then
    ready=1
    break
  fi
  sleep 1
done
[ "$ready" = 1 ] || { echo "Dolphin server did not become ready" >&2; exit 1; }

status="$(cli status server)"
printf '%s\n' "$status"
python3 -c 'import sys; value = sys.stdin.read(); assert "status: running" in value; assert "/var/lib/dolphin/config/herdr-dev/sessions/docker-proof/herdr.sock" in value' <<EOF
$status
EOF
workspace_json="$(cli workspace create --cwd /tmp/dolphin-proof --label 'Docker proof')"
printf '%s\n' "$workspace_json"
printf '%s\n' "$workspace_json" | python3 -c 'import json,sys; assert json.load(sys.stdin)["result"]["type"] == "workspace_created"'

snapshot="$(cli api snapshot)"
printf '%s\n' "$snapshot" | python3 -c '
import json, sys
value = json.load(sys.stdin)
snapshot = value["result"]["snapshot"]
assert snapshot["protocol"] == 20
assert len(snapshot["workspaces"]) == 1
assert snapshot["workspaces"][0]["label"] == "Docker proof"
print("isolated snapshot: ok")
'

cli pane run w1:p1 python3 /usr/local/bin/fake-agent.py
wait_for_fake_agent
if ! ready_wait="$(cli pane wait-output w1:p1 --match FAKE_AGENT_READY --timeout 5000 2>&1)"; then
  printf '%s\n' "$ready_wait" >&2
  exit 1
fi
printf '%s\n' "$ready_wait"
printf '%s\n' "$ready_wait" | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert value["result"]["matched_line"] == "FAKE_AGENT_READY"
assert value["result"]["read"]["source"] == "recent_unwrapped"
'
ready_read="$(cli pane read w1:p1 --source visible --lines 30 --format text)"
printf '%s\n' "$ready_read"
printf '%s\n' "$ready_read" | python3 -c '
import sys
assert "FAKE_AGENT_READY" in sys.stdin.read()
'


cli pane report-agent w1:p1 --source dolphin-test --agent codex --state idle
snapshot="$(cli api snapshot)"
printf '%s\n' "$snapshot" | python3 -c '
import json, sys
value = json.load(sys.stdin)
agent = value["result"]["snapshot"]["agents"][0]
assert agent["pane_id"] == "w1:p1"
assert agent["agent_status"] == "idle"
assert agent["cwd"] == "/var/lib/dolphin/home"
print("agent ownership: ok")
'

if ! prompt_result="$(cli agent prompt w1:p1 "docker prompt" 2>&1)"; then
  printf '%s\n' "$prompt_result" >&2
  exit 1
fi
printf '%s\n' "$prompt_result"
if ! done_wait="$(cli pane wait-output w1:p1 --match "FAKE_AGENT_DONE docker prompt" --timeout 5000 2>&1)"; then
  printf '%s\n' "$done_wait" >&2
  exit 1
fi
printf '%s\n' "$done_wait"
# Recent reads count rendered rows, including the blank rows below a fresh prompt.
agent_read="$(cli agent read w1:p1 --lines 40 --format text)"
printf '%s\n' "$agent_read"
printf '%s\n' "$agent_read" | python3 -c '
import sys
assert "FAKE_AGENT_DONE docker prompt" in sys.stdin.read()
print("prompt and output: ok")
'
preview="$(
  $compose exec --no-TTY dolphin-server env \
    HERDR_BIN_PATH=/usr/local/bin/dolphin \
    HERDR_SESSION=docker-proof \
    python3 -c '
import sys
sys.path.insert(0, "/opt/dolphin-board")
import board

snapshot = board.snapshot()
items = board.board_items(snapshot)
assert ("agent", "w1:p1") in items, items
preview = board.output_preview("w1:p1")
assert "FAKE_AGENT_DONE docker prompt" in preview, preview
print("workboard preview: ok")
'
)"
printf '%s\n' "$preview"

plugin_link="$(cli plugin link /opt/dolphin-board --enabled)"
printf '%s\n' "$plugin_link"
board_open="$(cli plugin pane open \
  --plugin reoring.dolphin-board \
  --entrypoint board \
  --placement overlay \
  --focus)"
printf '%s\n' "$board_open"
board_pane="$(
  printf '%s\n' "$board_open" | python3 -c '
import json
import sys

value = json.load(sys.stdin)
print(value["result"]["plugin_pane"]["pane"]["pane_id"])
'
)"
printf '%s\n' "$board_pane" | python3 -c '
import sys

assert sys.stdin.read().strip()
'
wait_for_board_pane

board_screen="$(cli pane read "$board_pane" --source visible --format text)"
printf '%s\n' "$board_screen"
printf '%s\n' "$board_screen" | python3 -c '
import sys

value = sys.stdin.read()
assert "DOLPHIN WORKBOARD" in value
assert "Docker proof" in value
'
echo "workboard smoke: ok"

cli pane send-keys "$board_pane" j
agent_selected=0
for _ in $(seq 1 50); do
  board_screen="$(cli pane read "$board_pane" --source visible --format text 2>/dev/null || true)"
  if printf '%s\n' "$board_screen" | python3 -c '
import sys

value = sys.stdin.read()
assert any("▶" in line and "w1:p1" in line for line in value.splitlines())
'; then
    agent_selected=1
    break
  fi
  sleep 0.1
done
printf '%s\n' "$board_screen"
printf '%s\n' "$agent_selected" | python3 -c '
import sys

assert sys.stdin.read().strip() == "1"
'
echo "workboard smoke: ok"

cli pane send-keys "$board_pane" o
if ! output_wait="$(cli pane wait-output "$board_pane" \
  --match "Output:" --source visible --timeout 5000 2>&1)"; then
  printf '%s\n' "$output_wait" >&2
  exit 1
fi
printf '%s\n' "$output_wait"
board_screen="$(cli pane read "$board_pane" --source visible --format text)"
printf '%s\n' "$board_screen"
printf '%s\n' "$board_screen" | python3 -c '
import sys

value = sys.stdin.read()
assert "Output:" in value
assert "FAKE_AGENT_DONE docker prompt" in value
'
echo "workboard smoke: ok"

cli pane send-keys "$board_pane" p
cli pane send-text "$board_pane" "board prompt"
cli pane send-keys "$board_pane" enter
if ! board_done_wait="$(cli pane wait-output w1:p1 \
  --match "FAKE_AGENT_DONE board prompt" --timeout 5000 2>&1)"; then
  printf '%s\n' "$board_done_wait" >&2
  exit 1
fi
printf '%s\n' "$board_done_wait"
printf '%s\n' "$board_done_wait" | python3 -c '
import json
import sys

value = json.load(sys.stdin)
assert "FAKE_AGENT_DONE board prompt" in value["result"]["matched_line"]
'
echo "workboard smoke: ok"

cli pane send-keys "$board_pane" q
board_exited=0
for _ in $(seq 1 50); do
  if board_info="$(cli pane process-info --pane "$board_pane" 2>&1)"; then
    if printf '%s\n' "$board_info" | python3 -c '
import json
import sys

value = json.load(sys.stdin)
processes = value["result"]["process_info"]["foreground_processes"]
assert any(process["argv"] == ["python3", "board.py"] for process in processes)
'; then
      sleep 0.1
      continue
    fi
  fi
  board_exited=1
  break
done
printf '%s\n' "$board_info"
printf '%s\n' "$board_exited" | python3 -c '
import sys

assert sys.stdin.read().strip() == "1"
'
echo "workboard smoke: ok"

echo "Docker Dolphin isolation: ok"
