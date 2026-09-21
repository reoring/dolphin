# Real-agent dogfooding

Run Dolphin with real agents (Codex, Claude Code) without touching the Herdr
you already use for daily work.

## Isolation

`scripts/dogfood/dolphin-dogfood` puts everything under one root
(`~/.local/state/dolphin-dogfood` by default; override with
`DOLPHIN_DOGFOOD_ROOT`):

| Concern     | Location                                             |
| ----------- | ---------------------------------------------------- |
| config      | `<root>/config/<app-dir>/config.toml`                 |
| socket      | `<root>/config/<app-dir>/sessions/<session>/herdr.sock` |
| state/cache | `<root>/state`, `<root>/cache`                        |
| worktrees   | `<root>/worktrees` (`[worktrees] directory`)          |
| session     | `dolphin-dogfood` (`DOLPHIN_DOGFOOD_SESSION`)         |

`HOME` is left untouched so agents keep their own credentials. The launcher
refuses to start when `HERDR_ENV`, `HERDR_SOCKET_PATH`, or
`HERDR_CLIENT_SOCKET_PATH` is set, when the root is under `~/.config`, or when
`run` has no terminal. `<app-dir>` is `herdr-dev` for debug builds and `herdr`
for release builds; the launcher asks the binary.

## Procedure

Use a terminal that is **not** a pane of your daily Herdr (an SSH session or a
plain terminal emulator). Nested Herdr is rejected.

```sh
scripts/dogfood/dolphin-dogfood check        # resolved paths, server status
scripts/dogfood/dolphin-dogfood run          # start the Dolphin TUI
# in another terminal, same isolation:
scripts/dogfood/dolphin-dogfood link-board   # once; then open the Workboard
scripts/dogfood/dolphin-dogfood cli plugin pane open \
  --plugin reoring.dolphin-board --entrypoint board --placement overlay --focus
```

Set `DOLPHIN_BIN` to use a different binary and `DOLPHIN_AGENT_COMMAND`
(e.g. `codex`) before `run` so `n` in the Workboard starts that agent in the
new worktree.

## What to record

Keep findings in the session notes: agent detection/status accuracy, prompt
routing, output preview usefulness, the `n`/`d`/`D` loop, and anything the
overlay pane cannot express (this drives the native-port decision).

Stop with `scripts/dogfood/dolphin-dogfood cli server stop`; it only stops the
sandbox session.
