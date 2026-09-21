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

echo "Docker Dolphin isolation: ok"
