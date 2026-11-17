# Harness core

The core is the small, sealed part of the development harness that every repository of the family shares: the `dev` dispatcher, its mise pins and a CI skeleton. It lives in `harness/`. This page records what the core contains, what was left out of it, and how to operate and change it.

Status: first half of the core (session 19). The guard script, the gate wrapper and the agent bindings arrive with session 20; `./dev sync` with session 23.

## Inventory of the imported harness

`harness/` was imported from the toolkit's single-root layout without edits (session 16). Most of it is the toolkit's own Python development harness, which is not part of the core. Line counts were measured on 2026-11-17.

| Path | Lines | Decision |
|---|---|---|
| `harness/scripts/dev` | 33 | Replaced by the new `harness/dev` dispatcher. The old launcher is not wired to anything. |
| `harness/scripts/dev.py`, `verify-agent.py`, `verify-agent-concurrency.py` | 2,049 | Toolkit-specific gates and agent probes. Not core. Left untouched and unwired; their fate is a question for PA (see "Open questions"). |
| `harness/tests/` (five files) | 1,902 | Tests of the files above. Same fate. |
| `harness/config/development.json`, `specifications.json` | 164 | Toolkit gate table and the spec list. `specifications.json` is input to session 22 (`specs.lock`). |
| `harness/config/toolchain.json` | 38 | **Removed in this session.** It was a minimum-version check; mise pins replace it. |
| `harness/docs/` (six pages), `harness/.github/` | 934 | Describe the toolkit harness. Session 23 (harness review) decides. |
| `harness/.claude/settings.json`, `harness/.codex/hooks.json` | 100 | Bindings and guard wiring. Wait for session 20. |
| `harness/pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore` | 437 | Python environment of the toolkit harness. Not core. |

Total imported: 5,662 lines. The core after this session is the new files only (see "Line count" in the tracker); the target for the whole core is about 600 lines.

## What the core does

`./dev` is the single entry point. Verbs in this half:

| Verb | Effect |
|---|---|
| `setup` | Installs the locked mise tools (`mise install --locked`). The only verb that installs anything. |
| `check` | Verifies that every tool named in `harness.toml` resolves under mise, and prints each version and path. |
| `ci` | `check`, then every check listed in `harness.toml`, in order. Stops at the first failure. |
| `x <command…>` | Runs any command under the pinned tools. |

Rules, from report 2.4:

- `./dev` re-runs itself under `mise exec --locked` before doing anything, so no tool comes from the shell.
- It finds mise by `PATH`, then in the usual install locations, because hooks and scheduled jobs run with a minimal `PATH`.
- It fails closed: a missing mise, or a tool resolved outside mise's directories, stops it with one line. There is no fallback to a system version.
- Nothing is installed in passing: `auto_install` is off in `mise.toml`.

## Open questions

- **The toolkit's Python harness** (`harness/scripts/dev.py`, `verify-agent*.py`, `harness/tests/`, `harness/config/development.json`, the six docs): about 4,900 lines that are not part of the core. This session leaves them in place, unwired. Delete them, move them under `plugins/pa-toolkit/`, or keep them as toolkit tooling? Decided by PA, most likely in session 23.
