# Harness core

The core is the small, sealed part of the development harness that every repository of the family shares: the `dev` dispatcher, its mise pins and a CI skeleton. It lives in `harness/`. This page records what the core contains, what was left out of it, and how to operate and change it.

Status: the dispatcher and CI skeleton (session 19); the gate wrapper, the guard, the agent bindings and the GitHub App token script (session 20). `./dev sync` arrives with session 23.

| File | Role |
|---|---|
| `harness/dev`, root `dev` | The dispatcher (below). |
| `harness/conf.awk` | The one parser of `harness.toml`. |
| `harness/gate` | The release gate ('Gate wrapper'). |
| `harness/guard`, `harness/bindings/` | The pre-tool-use guard and its three binding templates ('Guard'). |
| `harness/gh-token.sh`, `harness/gh-token.md` | Agents' GitHub identities: a one-hour App token per command, and PA's token behind a Keychain prompt ('Token script'). |
| `harness.toml`, `mise.toml`, `mise.lock` | Settings and pins, per repository. |

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
| `harness/.claude/settings.json`, `harness/.codex/hooks.json` | 100 | The toolkit harness's own hook wiring (`scripts/dev hook …`), loaded by nothing here. Not the core's bindings, which are new in `harness/bindings/` (session 20). They go with the toolkit's Python harness (see "Open questions"). |
| `harness/pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore` | 437 | Python environment of the toolkit harness. Not core. |

Total imported: 5,662 lines. The core after this session is the new files only (see "Line count" in the tracker); the target for the whole core is about 600 lines.

## What the core does

`./dev` is the single entry point:

| Verb | Effect |
|---|---|
| `setup` | Installs the locked mise tools (`mise install --locked`). The only verb that installs anything. |
| `check` | Verifies that every tool named in `harness.toml` resolves under mise, and prints each version and path. |
| `ci` | `check`, then every check listed in `harness.toml`, in order. Stops at the first failure. |
| `gate [<sha>]` | The read-only checks of the release gate ('Gate wrapper'). |
| `apply`, `deploy` | The release, in a repository with a `[gate]` table; handed to `harness/gate` before any re-run. |
| `x <command…>` | Runs any command under the pinned tools. |

Rules, from report 2.4:

- `./dev` re-runs itself under `mise exec --locked` before doing anything, so no tool comes from the shell.
- It finds mise by `PATH`, then in the usual install locations, because hooks and scheduled jobs run with a minimal `PATH`.
- It fails closed: a missing mise, or a tool resolved outside mise's directories, stops it with one line. There is no fallback to a system version.
- Nothing is installed in passing: `auto_install` is off in `mise.toml`.

## `harness.toml`

At the repository root. A restricted TOML subset, parsed by `harness/conf.awk` for both `harness/dev` and `harness/gate` (the `[gate]` table is described under 'Gate wrapper'); anything outside it is refused with the line number, so a typo cannot silently drop a check.

```toml
profile = "plugin"                         # plugin | tool | house-code | live-config
tools = ["python3", "shellcheck"]          # commands that must resolve under mise
[checks]                                   # run in order by `./dev ci`, each through `bash -c`
unit-tests = "python3 -B -m unittest discover -s tests -v"
```

Values are single-line strings or arrays of strings and may not contain double quotes or backslashes. `tools` lists command names as found on `PATH` (`python3`), not mise tool names (`python`). Repo-specific checks stay in the repository; `./dev ci` only runs what this file lists.

## Pins

`mise.toml` pins every tool that `./dev ci` calls; `mise.lock` holds checksums for `macos-arm64` and `linux-x64`. Settings in `mise.toml` turn every implicit install off. To change a pin, edit `mise.toml`, run `mise lock --platform macos-arm64,linux-x64`, then `./dev setup`, and commit both files. `config/toolchain.json` (a minimum-version check that pinned nothing) is gone; mise is the single source of tool versions.

## Tests

`tests/test_dev.py` runs the real dispatcher in subprocesses with a hand-built environment (minimal `PATH`, no `DEV_UNDER_MISE`). It covers: tools resolved under mise from a hook's `PATH`; a tool outside mise refused; a preset `DEV_UNDER_MISE` not bypassing verification; `ci` order and stop at first failure; every `harness.toml` refusal; the usage message; a missing mise. `tests/test_gate.py` covers every refusal of the gate ('Gate wrapper'), `tests/test_guard.py` the guard in the three payload shapes and the bindings ('Guard'); the guard tests need `jq` on the system `PATH`. The suite needs the pinned tools: run `./dev setup` first.

## Open questions

- **The toolkit's Python harness** (`harness/scripts/dev.py`, `verify-agent*.py`, `harness/tests/`, `harness/config/development.json`, the six docs): about 4,900 lines that are not part of the core. This session leaves them in place, unwired. Delete them, move them under `plugins/pa-toolkit/`, or keep them as toolkit tooling? Decided by PA, most likely in session 23.

## Cloud sessions

Checked 2026-11-17 in a cloud session on this repository:

- **mise is not installed by default.** `./dev setup` and every other verb stop with `mise not found` and install nothing. This is the fail-closed behaviour of report 2.4, not a bug.
- **mise can be installed there.** The official installer put mise 2026.11.9 in `~/.local/bin/mise`, one of the locations `./dev` searches, so no `PATH` or shell-profile change is needed.
- **`./dev setup` then installs the three pinned tools** (python 3.13.18, shellcheck 0.11.0, actionlint 1.7.12) and `./dev check` passes with every tool under mise's install directory.
- `./dev ci` also passes there (27 tests, validator, shellcheck, actionlint).
- mise warns that actionlint is deprecated in favour of the maintained fork `jactionlint`. The pin is unchanged; moving to the fork is a separate decision.

Cloud recipe: install mise with its official installer, then `./dev setup`.

## Gate: what the two step-0 wrappers share

Session 20 compared the gates of `network-config` (`./dev apply`, Terraform) and `ha-config` (`./dev deploy`, SSH to the host), both at `origin/main` with sessions 04b and 13c merged. Both were written as one design, so most of the code is the same line for line.

Common to both, and therefore in the core (`harness/gate`):

| Part | Behaviour |
|---|---|
| Strict re-run | The release verb never trusts the caller: mise only from its fixed install locations (never `PATH`), a system `PATH`, a named list of variables (everything else dropped, exported functions too), then `mise exec --locked`. The second stage is marked by an argument, not by the environment. |
| Second-stage check | Nothing dropped may be back (a hand-typed second stage, or a mise `[env]` section). |
| Variables kept | Home, user, temp, terminal, locale, `MISE_STATE_DIR`; for the gate the bot token (`GH_TOKEN` and the `GIT_CONFIG_*` entries of `gh-token.sh`) and the proxy settings. |
| Settings | `repo`, `merger`, `guarded_paths`, validated, in a committed file that is parsed, never sourced. |
| 1. Clean tree | No `assume-unchanged` or `skip-worktree` entry; `git status` empty, untracked files included; no ignored file that mise would load (`mise.local.toml`, `.tool-versions`, `.mise/`, `.config/`). |
| GitHub token | Refuses at once without `GH_TOKEN`, before git can prompt. |
| 2. Tip | Fetch with every prompt off; `HEAD` = `origin/main` = `main` on GitHub. |
| 4. Merged by | The commit is the merge commit of exactly one PR into `main`, merged by `merger`. |
| 5. Descent | `HEAD` descends from the last released commit when this clone has it. Record in `<git common dir>/dev-<verb>/` (`last`, `log`), never committed. |
| Guarded diff | Diff of the guarded paths since the last release (or their recent history when there is none), confirmed by PA on `/dev/tty`. |
| Read-only verb | `./dev gate`: the checks on `HEAD` and the descent; `./dev gate <sha>`: CI and merged-by for that commit. |
| Record | Written only after the release succeeded. |

Repository-specific, and therefore supplied by the repository:

| Part | `network-config` | `ha-config` |
|---|---|---|
| Verb | `apply`, no arguments (plus `plan`, ungated) | `deploy <mode> [options]` |
| 3. CI source | Check runs for the commit, required check names from one App | Workflow runs of event `push` for the commit (scheduled runs also attach to `main`'s tip), required workflow paths |
| Ignored files the release would load | `cloudflare/*.tf`, `*.tf.json`, `*.auto.tfvars`, `terraform.tfvars.json` | none (the commit itself reaches the host) |
| Extra variable kept | the Cloudflare read token | none |
| Extra state | checksum of the ignored `terraform.tfvars`, confirmed when new or changed | the SSH target, written once by hand |
| Release | HCP token (prompt 1), plan on the read token, tree re-checked, confirm, write token (prompt 2), apply | deploy key into a throwaway `ssh-agent` (one prompt), forced command, host `HEAD` must equal the commit; `--check` releases nothing and records nothing |
| Confirmation | always needs a terminal | a terminal only when guarded files changed (better: an unchanged gate needs none) |

The core keeps `ha-config`'s two refinements (terminal only when something changed; `push`-event runs) as options rather than dropping either: `ci = "check-runs"` or `"workflow-runs"` in `harness.toml`.

## Gate wrapper

`harness/gate` holds every common check above; the repository supplies only its release command and a `[gate]` table in `harness.toml`. Report 2.3 item 2 is the design; this section is the contract.

### Verbs

| Command | Effect |
|---|---|
| `./dev gate` | Read-only, no credential: checks 1 to 4 on `HEAD`, then the descent. Runs under the ordinary `mise exec` re-run, so it works in an agent shell. |
| `./dev gate <sha>` | Read-only: CI and merged-by for that commit only. |
| `./dev apply` or `./dev deploy` (the `verb` of `harness.toml`) `[args…]` | The release: strict re-run, every check, the guarded diff, then the release command with `args`. The other verb is refused. |
| `harness/gate tree` | Check 1 only, no network. For a release command that must re-check the tree after a long step (a Terraform plan). |

Both verbs need the bot's read token: run them as `harness/gh-token.sh claude -- ./dev …`. Without `GH_TOKEN` the gate refuses before git can prompt.

### Settings

```toml
tools = ["gh", "shellcheck"]                # must include gh: the gate reads GitHub with it
[gate]
repo = "owner/name"
merger = "login"                            # the only login whose merge releases a commit
verb = "deploy"                             # apply | deploy
release = "scripts/deploy.sh"               # executable, relative to the root, no ..
ci = "workflow-runs"                        # check-runs | workflow-runs
required = [".github/workflows/ci.yml"]     # check names (check-runs) or workflow paths
guarded = [".github", ".harness", "harness.toml", "mise.toml", "mise.lock", "scripts/deploy.sh", ".claude", ".codex", ".agents", ".githooks"]
loaded = ["cloudflare/*.tf"]                # optional: ignored files the release would load (globs)
keep_env = ["CLOUDFLARE_API_TOKEN_READ_ALL"]  # optional: variables the release command needs
```

`checks_app` (the App slug of the required check runs, usually `github-actions`) is required with `check-runs` and refused with `workflow-runs`. Every key is validated; a missing or malformed one stops the gate with its name. `guarded` must list everything that decides what the gate and the release do: CI, the core, the pins, the release command, the token script, the agent permissions and hooks.

### The release command

Called from the repository root as `<release> [args…]`, after every check and PA's confirmation, with:

- `GATE_SHA`: the commit to release (`HEAD`, the tip of `main`);
- `GATE_LAST`: the last released commit, empty when there is none;
- `GATE_RECORD_DIR`: `<git common dir>/dev-<verb>/`, where it may keep its own state (Terraform's variables checksum, the SSH target);
- the variables of the strict re-run plus `keep_env`, and **no** `GH_TOKEN` and no `GIT_CONFIG_*` entries (they carry the bot token).

It validates its own arguments before reading any credential, reads its credentials behind a Keychain prompt, and confirms on `/dev/tty` if it needs to. Its exit code decides the record:

| Exit | Meaning | Record |
|---|---|---|
| 0 | released | `last` = `GATE_SHA`, and a line in `log` |
| 3 | passed, nothing released (a dry run such as `deploy --check`) | nothing |
| anything else | failed | a `failed-exit-<n>` line in `log`; `last` unchanged |

### The strict re-run

The release verb is handed from `harness/dev` to `harness/gate` before `dev`'s own `mise exec` re-run. Stage 1 finds mise only at `/opt/homebrew/bin`, `/usr/local/bin` or `~/.local/bin` (never `PATH`), sets a system `PATH`, drops every variable outside a named list and every exported function, and re-runs under `mise exec --locked`. Stage 2 is marked by an argument and refuses any variable outside the same named list plus what bash, macOS and mise add (`PWD`, `OLDPWD`, `SHLVL`, `_`, `__CF_USER_TEXT_ENCODING`, `__MISE_*`): a named list, not a deny list (finding F6 of session 04), so a mise `[env]` section or a hand-typed second stage is caught whatever it sets. Stage 2 then runs `harness/dev check`, so every tool of `harness.toml` must resolve under mise.

In an agent's sandbox, the git proxy lives in `GIT_CONFIG_PARAMETERS`, which the re-run drops: a release from an agent shell needs the sandbox off (tracker finding of session 04b). `./dev gate` keeps it and works inside the sandbox.

### Refusal cases and their tests

Each refusal is one line, `dev: refused: …`, exit 1. `tests/test_gate.py` has at least one test for each:

| Check | Refused when |
|---|---|
| Settings | no `[gate]` table; bad `repo`, `merger`, `verb`, `release` (missing, not executable, `..`), `ci`, `checks_app`, `required`, `guarded`, `loaded`, `keep_env`; `gh` not in `tools`; an unknown key (`conf.awk`) |
| Re-run | the other release verb; a variable outside the named list in stage 2 (a hand-typed `--stage2`) |
| 1. Tree | an `assume-unchanged` or `skip-worktree` entry; a modified or untracked file; an ignored file mise loads (`mise.local.toml`, `.tool-versions`, `.config/`); an ignored file matching `loaded` |
| Token | no `GH_TOKEN` |
| 2. Tip | `origin` cannot be fetched; `HEAD` is not `origin/main`; GitHub's `main` differs or cannot be read |
| 3. CI | runs cannot be read; no run; a run not completed; a run neither green, neutral nor skipped; a required run missing, or from another App |
| 4. Merged by | PRs cannot be read; not the merge commit of a PR into `main`; several PRs; merged by anyone but `merger`; the PR cannot be read |
| 5. Descent | a malformed record; `HEAD` does not descend from the last released commit |
| 6. Guarded diff | guarded files changed (or no record) and no terminal; PA does not type `yes` |
| Release | the release command fails (logged, not recorded) |

The tests replace GitHub with a `gh` shell function that answers from files: they test the gate's decisions, not `gh`'s `--jq` filters, which are unchanged from the two live gates where they were tested against GitHub. The re-run tests use the real mise and are skipped where mise is not in a fixed location.

### Moving a live repository to it (sessions 26 and 27)

`dev.conf` becomes the `[gate]` table; `scripts/` gets the release command, cut from the repository's `./dev` (`run_apply` and the `tfvars` checks for `network-config`; `read_target`, `release_deploy` and the host-`HEAD` check for `ha-config`, with `--check` exiting 3). The record directories keep their names (`dev-apply`, `dev-deploy`), so the last released commit carries over.

## Guard

`harness/guard` is the one pre-tool-use hook of the core, for Claude Code, Codex and Antigravity (report 2.2, 'Hooks'). It reads the shell command an agent is about to run and denies:

| When | What | Why |
|---|---|---|
| Always | a push to `main` or `master`; a force push (`--force`, `-f`, `--force-with-lease`, `+refspec`, `--mirror`); a remote branch deletion (`--delete`, `-d`, `:branch`, `--prune`); `--no-verify` on any git command; `gh pr merge`, `gh pr ready`, the merge API | PA merges; the git hooks run `./dev check` |
| Where nobody answers a prompt | `./dev apply`, `./dev deploy` (quoted, through a path, `mise exec`, `gh-token.sh` or `bash -c` too) and `gate release` / `gate --stage2` | the release confirms on the terminal and prompts in the Keychain |

"Where nobody answers a prompt" means: a Claude Code cloud session (`CLAUDE_CODE_REMOTE=true`); a permission mode other than `default`, `acceptEdits`, `plan` or `auto` (`bypassPermissions`, where session 12 saw an `ask` rule not prompt; `dontAsk`; a missing mode); and Antigravity, whose payload carries no mode. Everything else passes: the guard is not a permission system, and the repository's own rules and hooks (the connector guards of `ha-config`, for instance) stay beside it.

It fails closed: no `jq`, a payload it cannot read or an unknown agent denies the call. It uses bash builtins and `jq` only (`/usr/bin/jq` ships with macOS; CI runners have it). Commands are matched as text, one simple command at a time (split on `;`, `&`, `|` and newlines), so a commit message that quotes a denied command is denied too: reword it. Early warning, not the boundary (report 2.3): an agent with a shell can edit the guard or its bindings, and a hook that cannot start (missing file, not executable) lets the call through in all three agents.

### Bindings

Templates in `harness/bindings/`, copied to the repository root by `./dev sync` (session 23). They call `.harness/guard`, the synced location; this repository's own copies call `harness/guard`, and `tests/test_guard.py` checks that the two agree.

| Agent | File | Matcher | Payload read | Deny |
|---|---|---|---|---|
| Claude Code | `.claude/settings.json` | `Bash` | `tool_name`, `tool_input.command`, `permission_mode` | exit 2, reason on stderr |
| Codex | `.codex/hooks.json` | `Bash` (also matches `exec_command`) | same fields as Claude Code | exit 2, reason on stderr |
| Antigravity | `.agents/hooks.json` | `run_command` | `toolCall.name`, `toolCall.args.CommandLine` | `{"decision":"deny","reason":…}` on stdout, exit 0 |

Codex loads project hooks only in a trusted project, and only after the hooks themselves are reviewed and trusted (`/hooks`); a changed hook is skipped until it is trusted again. Codex and Antigravity run the command from the session's directory, so their bindings find the root with `git rev-parse --show-toplevel`.

Delivery, checked by hand on 2026-11-17 (session 20) with `git push --dry-run origin HEAD:main`, which every agent refused with the guard's reason:

| Agent | Version | Where | Result |
|---|---|---|---|
| Claude Code | `claude -p --permission-mode default` | linked worktree | denied |
| Antigravity | `agy` 1.5.10 | linked worktree | denied ("tool call denied by pre-tool hook") |
| Codex | codex-cli 0.169.0 | plain clone, trusted, hook trusted in `/hooks` | denied ("Command blocked by PreToolUse hook") |

**Codex does not load project hooks in a linked git worktree.** In a worktree of a trusted checkout, `/hooks` listed nothing, and `codex exec --trust` saved no trust for the worktree's path: Codex takes the project to be the main checkout and reads `.codex/` there, not in the worktree. In a plain clone of the same commit the hook loaded. So, in Codex, a branch's hook changes cannot be tried from its worktree, and a worktree session runs the hooks of the main checkout's branch (usually `main`). Codex lists the hook as "unnamed hook"; that is cosmetic.

## Token script

`harness/gh-token.sh` mints a one-hour GitHub App installation token for one repository, runs one command as `<app>[bot]` and revokes the token; `pa -- <command>` releases PA's own token through a Keychain prompt for one command. It moved from `ha-config/scripts/` in session 20 with no change in behaviour: only two mentions of its documentation's path differ (checked by `diff`, and by a `--info` read-back from the new place). Setup, rights and failure behaviour: `harness/gh-token.md`. Until a live repository syncs the core, its own copy stays and either copy serves any repository. The gate's 'no GitHub token' refusal names it.

## Agent files

`AGENTS.md` is canonical and stays under 24,000 bytes (Antigravity's limit; Codex allows 32 KiB). It holds a short shared block between `harness:shared:begin` and `harness:shared:end`, the same text in every repository, then the repository's own rules; depth goes into skills. `CLAUDE.md` is `@AGENTS.md` plus Claude-only notes. Claude Code reads `AGENTS.md` alone when there is no `CLAUDE.md`, but the stub stays. Templates for the block, the stub and the symlink command: `harness/templates/`.

Repository skills live in `.agents/skills/<name>/`. Claude Code does not load that folder directly; it loads it through `.claude/skills`, one committed directory symlink to `../.agents/skills`.

**Probe** (the first entry of the workaround register; re-run it to see whether the symlink can go). In a throwaway project holding one `SKILL.md` under `.agents/skills/<name>/`, run `claude -p "ok" --model haiku --output-format stream-json --verbose` and look for the name in the `skills` list of the `system`/`init` event. Result, 2026-11-17, macOS terminal: **absent** without the symlink, **listed** with it.

This repository has no skills of its own yet: its two helpers are slash commands in `.claude/commands/`, so `.agents/skills/` holds only a `.gitkeep`.

**Desktop app and cloud session** (2026-11-17, branch `kit-agent-files`, read-only prompt, Claude Code; version not shown by either surface). Both loaded `AGENTS.md` (the shared block) and the Claude-only section of `CLAUDE.md`; both listed `bump-plugin` and `new-plugin-skeleton` (shown as skills, not as commands); both showed `.claude/skills -> ../.agents/skills`; both refused `git push --dry-run origin HEAD:main` through the guard hook. The desktop app was tried in its local-session option (a local worktree, Code tab); its cloud-session option is the cloud result. Because the repository has no skills yet, the probe shows that the symlink survives checkout on both surfaces, not that a skill under `.agents/skills/` loads there; only the terminal probe (throwaway project) shows that. A guard refusal blocks the whole Bash call when the denied command is chained with others: run it alone.

## Path filters

`validate.yml` keeps one always-running job, `Marketplace validation` (the required check). A `changes` job lists the plugins whose files differ from the PR base, and each plugin's own job runs only when its path changed; pushes to `main` and manual runs check every plugin. See `docs/protected-main.md`. This replaces the PR check planner of the imported Python harness and the per-agent acceptance matrix, which the core does not carry.
