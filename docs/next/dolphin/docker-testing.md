# Isolated Docker testing

The Docker harness builds Dolphin inside the image and exercises it without contacting
production Herdr. It is safe to run from a checkout with no host `target/` binary or
Nix installation, and never connects to `~/.config/herdr` or the production socket.

## Isolation boundary

The only service is `dolphin-server` (container `dolphin-dolphin-server-1`).

Compose supplies these paths and values; the entrypoint uses the same defaults:

- `HOME=/var/lib/dolphin/home`
- `XDG_CONFIG_HOME=/var/lib/dolphin/config`
- `XDG_STATE_HOME=/var/lib/dolphin/state`
- `XDG_CACHE_HOME=/var/lib/dolphin/cache`
- `XDG_RUNTIME_DIR=/var/lib/dolphin/runtime`
- `HERDR_CONFIG_PATH=/var/lib/dolphin/config/herdr/config.toml`
- session `docker-proof`
- socket `/var/lib/dolphin/config/herdr/sessions/docker-proof/herdr.sock`

The image contains `/usr/local/bin/dolphin`, built by the builder stage. Compose only
mounts the test entrypoint, fake agent, and `plugins/dolphin-board`; it does not mount
`/nix/store` or `target/debug/dolphin`.
The host HOME, production config/socket, and session `default` are never used.
The entrypoint rejects sockets outside `/var/lib/dolphin/` (exit 70), unsets
`HERDR_ENV` and `HERDR_CLIENT_SOCKET_PATH`, and disables update checks/onboarding.
Release builds use the `herdr` app directory; debug builds use `herdr-dev`.
Both the explicit session and inherited socket must resolve to the release path.

## Run

Do not run multiple copies: the single Compose project is shared.
Run these commands from the repository root. All Dolphin runtime operations go
through Compose; do not run `herdr` or `target/debug/dolphin` on the host.

```sh
docker compose -f compose.test.yaml down -v --remove-orphans
docker compose -f compose.test.yaml config --quiet
docker compose -f compose.test.yaml build
docker compose -f compose.test.yaml run --rm --entrypoint /usr/local/bin/dolphin dolphin-server --version
scripts/docker/test-dolphin-isolated.sh
docker compose -f compose.test.yaml down -v --remove-orphans
```

The builder uses `rust:1.96-bookworm` with Rust 1.96.1 and the official x86_64
Zig 0.15.2 tarball/checksum pinned in `docker/Dockerfile.test`. It runs
`cargo build --release --locked --bin dolphin`; the runtime installs Git and
Python 3 on Debian bookworm-slim. No host Rust or Zig toolchain is required.

The version command must print `herdr 0.8.2`. The runner owns cleanup with the same
`down` command on exit, including failures.

## What the runner proves

In order, the runner proves: server readiness and the isolated socket; a Git
fixture, workspace creation and a one-workspace API snapshot; fake-agent process
readiness; agent ownership reported as `codex`; prompt delivery and agent output;
Workboard snapshot preview; plugin link and focused overlay pane; visible
Workboard rendering; `j` selection; `o` output view; `p` prompt forwarding and
output; `k` workspace selection; `n` new task worktree creation with
`DOLPHIN_AGENT_COMMAND` starting the new root agent; `d` changed-file review;
`D` split-pane diff review and output; and `q` pane exit.
Success prints the snapshot, ownership, prompt/output and preview `: ok` markers; five
`workboard smoke: ok` markers, `new task: ok`, `diff review: ok`, and finally `Docker Dolphin isolation: ok`.

The fake agent emits `FAKE_AGENT_READY`, then `FAKE_AGENT_WORKING <prompt>` and
`FAKE_AGENT_DONE <prompt>`. It self-reexecs as `python3` with `HERDR_AGENT=codex`
when that variable is not `codex`: agent-input validation checks the foreground process
identity in `/proc/<pid>/environ`, not just the report-agent metadata.

## Read contracts and troubleshooting

`recent` reads count rendered rows from the bottom, including blank rows below a
fresh prompt. UI assertions must use `--source visible`, because `visible` is the
screen currently rendered for the pane.

If `agent_not_ready` appears, the foreground process may still be between the shell
and fake-agent exec. The runner waits for exact argv `python3 /usr/local/bin/fake-agent.py`
and then waits for `FAKE_AGENT_READY`; rerun after checking that the container is
healthy. If identity fails, inspect `pane process-info`: the foreground process must
be the self-reexecuted Python process with `HERDR_AGENT=codex`, not merely a reported
agent record.
