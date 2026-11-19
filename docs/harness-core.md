# Harness core

The core is the small, sealed part of the development harness that every repository of the family shares: the `dev` dispatcher, its mise pins and a CI skeleton. It lives in `harness/`. This page records what the core contains, what was left out of it, and how to operate and change it.

Status: the dispatcher and CI skeleton (session 19); the gate wrapper, the guard, the agent bindings and the GitHub App token script (session 20). `./dev sync`, the checksum check and the workaround register (session 23). Session 24c, from the phase 3 review (findings K6, K10, K14, K20 to K25): the gate's order, history check, fixed guarded set, environment checks and baseline; the core git hooks; the token script's `--read-only` and `--print`; sync by commit, with modes, refusing a differing root file.

| File | Role |
|---|---|
| `harness/dev`, root `dev` | The dispatcher (below). |
| `harness/conf.awk` | The one parser of `harness.toml`. |
| `harness/gate` | The release gate ('Gate wrapper'). |
| `harness/githooks/` | The core git hooks, `pre-commit` and `pre-push` ('Git hooks'). |
| `harness/guard`, `harness/bindings/` | The pre-tool-use guard and its three binding templates ('Guard'). |
| `harness/gh-token.sh`, `harness/gh-token.md` | Agents' GitHub identities: a one-hour App token per command, and PA's token behind a Keychain prompt ('Token script'). |
| `harness.toml`, `mise.toml`, `mise.lock` | Settings and pins, per repository. |

## Inventory of the imported harness

`harness/` was imported from the toolkit's single-root layout without edits (session 16). Most of it was the toolkit's own Python development harness, which is not part of the core. Total imported: 5,662 lines (measured 2026-11-17). Since session 23b, `harness/` holds the core only: every tracked file under it is named by `harness/core.files`.

| Path | Lines | What it did | What happened |
|---|---|---|---|
| `harness/config/toolchain.json` | 38 | Minimum tool versions. | Removed in session 19: mise pins replace it. |
| `harness/config/specifications.json` | 19 | The upstream spec list. | Removed in session 22: `tools/specs/watch.json` and `specs.lock` replace it. |
| `harness/scripts/dev`, `dev.py` | 925 | The toolkit's dispatcher: `check`, `ci`, `plan`, `specs`, `package`, `release-check`, `hook`, `worktree`, `install-hooks`, `format` and more. | Deleted in session 23b. Replaced by `harness/dev`, the path filters ('Path filters'), `specs.lock`, `scripts/plugin_zip.py` with `release.yml`, and the guard. |
| `harness/scripts/verify-agent.py`, `verify-agent-concurrency.py` | 1,153 | Real-client acceptance probes (the per-agent acceptance matrix). | Deleted in session 23b. Dropped on purpose (report 2.7); the workaround probes in `tools/probes/` cover what the register needs. |
| `harness/tests/` (five files, 91 tests) | 1,902 | Tests of the scripts above. They did not run from `harness/`: 49 errors and 9 failures. | Deleted in session 23b with the scripts. |
| `harness/config/development.json` | 137 | The toolkit's gate and impact table, read by `dev.py`. | Deleted in session 23b. |
| `harness/docs/` (six pages) | 850 | Development setup, architecture, hook scope, supported agents, acceptance plan and evidence. | Deleted in session 23b. This page describes the core. |
| `harness/.github/` | 84 | `release-checks.yml` and Copilot instructions; GitHub never ran them at this path. | Deleted in session 23b. |
| `harness/.claude/settings.json`, `harness/.codex/hooks.json` | 100 | Hook wiring to `scripts/dev hook …`, loaded by nothing here. | Deleted in session 23b. The core's bindings are in `harness/bindings/`. |
| `harness/pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore` | 437 | The uv environment of the scripts above. | Deleted in session 23b. |
| `tools/pa-devtools/` (13 files) | 1,292 | The toolkit's Python SDK (`planning`, `specifications`, `hooks`, `snapshots`, `source`); its only consumer was `harness/scripts/dev.py`. | Deleted in session 23b. |

Nothing referenced the deleted files outside themselves and this page: no workflow, no `harness.toml` entry, no root test, no plugin manifest. Every deleted file can be read at commit `60c18cd` (for example `git show 60c18cd:harness/scripts/dev.py`), and in the archived `pa-toolkit` repository.

Still open, outside this page: the `pa-toolkit` plugin's `config/release.json`, `AGENTS.md`, `README.md` and `skills/plugin-release/references/development.md` still name `./scripts/dev` and `release-checks.yml`. These have not existed relative to the plugin since session 16. Fixing them is a plugin change with its own version bump, left to a later session.

## What the core does

`./dev` is the single entry point:

| Verb | Effect |
|---|---|
| `setup` | Installs the locked mise tools (`mise install --locked`) and the core git hooks (`core.hooksPath`, 'Git hooks'). The only verb that installs anything. Runs in PA's terminal: the agent sandbox cannot write `.git/config`. |
| `check` | Verifies that every tool named in `harness.toml` resolves under mise, that a synced core matches its `CHECKSUMS`, and that the active git hooks are the core's; prints each tool's resolved version (`mise which --version`) and path, then runs the repository's own offline `check` command if `harness.toml` names one. |
| `ci` | The same tool and core verification and offline `check` command, then every check listed in `harness.toml`, in order. Stops at the first failure. Every check command runs as `bash -o pipefail -c`, so a failure early in a pipeline counts. |
| `gate [<sha>]` | The read-only checks of the release gate ('Gate wrapper'). `gate --baseline <sha>`: PA's recovery of the release record ('Baseline'). |
| `apply`, `deploy` | The release, in a repository with a `[gate]` table; handed to `harness/gate` before any re-run. |
| `x <command…>` | Runs any command under the pinned tools. |
| `<verb> [args…]` | A verb the repository declares in the `[verbs]` table of `harness.toml` (here `specs`). Runs under the pinned tools; arguments reach the command as positional parameters. |

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
check = "python3 -B tools/specs/specs.py check"   # optional: one offline command for `./dev check` and `./dev ci`
[verbs]                                    # optional: `./dev <name> [args…]`, same rules as a check
specs = "python3 -B tools/specs/specs.py"
```

`check` must contact nothing: it is what local hooks, PR runs and `main` runs share, so one commit gives one result everywhere. A verb name may not be one of the built-in verbs. Values are single-line strings or arrays of strings and may not contain double quotes or backslashes. A key given twice in one table, a blank string, and a blank array item or one containing whitespace are refused (arrays are read as space-separated words, so such an item would vanish or split; a required check name therefore may not contain a space). `tools` lists command names as found on `PATH` (`python3`), not mise tool names (`python`). Repo-specific checks stay in the repository; `./dev ci` only runs what this file lists.

## Git hooks

`harness/githooks/` (`.harness/githooks/` in a consumer) holds the core's two git hooks (finding K14; they keep what both live repositories' `.githooks/` did):

| Hook | Does |
|---|---|
| `pre-commit` | `./dev check`, then the repository's own `.githooks/pre-commit` if it is executable. |
| `pre-push` | Refuses a push to `main` or `master` (changes reach `main` through a PR PA merges), runs `./dev check`, then the repository's own `.githooks/pre-push` with the same arguments and ref lines on stdin. |

`./dev setup` sets `core.hooksPath` to `<core directory>/githooks`, a relative path, so each worktree runs its own checkout's copy. `./dev check` refuses any other active hooks path (unset in a fresh clone, or an old path into another checkout) and names `./dev setup`. A repository adds its own hooks as executable `.githooks/pre-commit` or `.githooks/pre-push`; the core hooks call them after their own work. Both live repositories' current `.githooks/` files duplicate the core hooks, so sessions 26 and 27 delete them when they sync. The hooks are a convenience, not a control: `--no-verify` skips them (the guard denies it to agents), and GitHub's protection of `main` is the control where it exists.

## Pins

`mise.toml` pins every tool that `./dev ci` calls; `mise.lock` holds checksums for `macos-arm64` and `linux-x64`. Settings in `mise.toml` turn every implicit install off. To change a pin, edit `mise.toml`, run `mise lock --platform macos-arm64,linux-x64`, then `./dev setup`, and commit both files. `config/toolchain.json` (a minimum-version check that pinned nothing) is gone; mise is the single source of tool versions.

## Tests

`tests/test_dev.py` runs the real dispatcher in subprocesses with a hand-built environment (minimal `PATH`, no `DEV_UNDER_MISE`). It covers: tools resolved under mise from a hook's `PATH`, with their versions; a tool outside mise refused; a preset `DEV_UNDER_MISE` not bypassing verification; `ci` order and stop at first failure; `pipefail` in check commands; every `harness.toml` refusal; the usage message; a missing mise; the git hooks from a fresh clone. Its other tests give git `core.hooksPath` through the environment, as after `./dev setup`, so they do not depend on how the running clone was set up. `tests/test_gate.py` covers every refusal of the gate ('Gate wrapper') and runs the release entry point end to end; `tests/test_gh_token.py` the token script without a Keychain or network; `tests/test_guard.py` the guard in the three payload shapes and the bindings ('Guard'); the guard and token tests need `jq` on the system `PATH`. The suite needs the pinned tools: run `./dev setup` first.

## Open questions

No question waits on PA. What the core accepts as limits, after session 24c (Codex rows C1, C4 and C19 of the phase 3 review, and what 24c left as is):

- **The prompt authorizes a credential, not a commit (C1).** The release command is an ordinary executable of the repository; the Keychain prompt releases a credential to it and does not bind PA's approval to the commit, the target or the operation. The gate's checks and PA's confirmation of the guarded diff stand in for that binding. A stronger design, an owner-controlled component outside the checkout that shows and binds the exact SHA and operation, is not built.
- **The checked commit and the executed files can drift (C4).** The gate reads `HEAD` and the working tree, not an immutable checkout of the verified SHA, and does not re-check GitHub's `main` at the moment of the release. The clean-tree check and the house receiver's exact-SHA fast-forward (`ha-config`) narrow the window; nothing closes it in the core.
- **Agents with a shell can still change the gate (C19, report 2.3 'What stays open').** The gate, the record in `.git/dev-<verb>/` and the hooks live in the clone; an agent with a shell on the Mac can edit them. Only the credential prompt holds; the gate shows PA what changed since the last release, and the guard refuses the obvious routes.
- **mise runs before the gate's first check (C2, remainder).** Stage 1 starts `mise exec`, which reads the configuration files before stage 2 can refuse what they add; a mise `_.source` script would already have run. Stage 2 then refuses any variable or `PATH` entry they added.
- **The read-only gate updates `origin/main` (C23).** `./dev gate` fetches `origin main`, which moves the remote-tracking ref; it writes nothing else.
- **The baseline stays in the clone (PA's choice, session 24c; C8).** See 'Baseline'.

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

This table is the common part as session 20 found it. Session 24c went beyond both live gates (the history since the last release, the fixed guarded set, the environment checks, the baseline and the order of a release): 'Gate wrapper' is the contract.

## Gate wrapper

`harness/gate` holds every common check above; the repository supplies only its release command and a `[gate]` table in `harness.toml`. Report 2.3 item 2 is the design; this section is the contract.

### Verbs

| Command | Effect |
|---|---|
| `./dev gate` | Read-only: checks 1 to 4 on `HEAD`, then check 5 (every change since the last release). Runs under the ordinary `mise exec` re-run, so it works in an agent shell. |
| `./dev gate <sha>` | Read-only: CI and merged-by for that commit only. |
| `./dev gate --baseline <sha>` | PA's recovery of a missing or unusable release record ('Baseline'). Needs a terminal and PA's `yes`; no GitHub token. |
| `./dev apply` or `./dev deploy` (the `verb` of `harness.toml`) `[args…]` | The release: strict re-run, every check, the guarded diff, `./dev check`, then the release command with `args`. The other verb is refused. |
| `harness/gate tree` | Check 1 only, no network. For a release command that must re-check the tree after a long step (a Terraform plan). |

Both verbs need the bot's read-only token: run them as `harness/gh-token.sh claude --read-only -- ./dev …` (`--read-only` asks GitHub for every permission at level read, finding K20). Without `GH_TOKEN` the gate refuses before git can prompt.

### Order of a release

Stage 2 runs, in this order (finding K20: nothing of the repository runs before its provenance is checked, and nothing of it runs with the GitHub credential):

1. the settings, the environment (named list, git entries, mise additions: 'The strict re-run'), the token, then the lock of the record directory;
2. checks 1 to 4 on `HEAD`; check 5, every change since the last release; check 6, the guarded diff and settings, confirmed by PA;
3. the GitHub credential is dropped (`GH_TOKEN` and the `GIT_CONFIG_*` entries);
4. `./dev check`: the repository's tools and its offline `check` command;
5. the release command.

Every network call (the fetch, each GitHub read) runs under a 60-second deadline that ends in a refusal, and every GitHub collection is read page by page to the end (findings C10, C23).

### Baseline

The record of the last release, `<git common dir>/dev-<verb>/last`, is the baseline from which check 5 counts. PA chose (session 24c, finding K23) to keep it in the clone rather than at the target:

- A missing record, a malformed one, or one whose commit is not in the clone is refused. Nothing falls back to recent history.
- The only way to set it outside a release is `./dev gate --baseline <sha>` in PA's terminal: the commit must be in the clone and on `origin/main`; the gate shows it and the record it replaces (read as it is, so a malformed record can be replaced: it is the refusal's own way out), and PA types `yes`. It is logged in `log` as `baseline`.
- A release writes it only after the release command succeeds, and only if it still holds what the run read at its start (written whole, then renamed).
- A `lock` in the record directory serialises releases and baseline changes in one clone. It is a symbolic link whose target is the owner's PID, created with `ln -s`, so the lock and its owner appear in one atomic step and a second run never sees a live lock without a PID (Codex review of #102). A lock whose process is gone is taken over; anything else at that path (a directory, a link that is not a PID) is refused and left alone; each run removes only its own lock. Two runs taking over the same stale lock at the same instant remain a narrow race.

When a live repository moves to the core (sessions 26 and 27), its record directory keeps its name, so the existing `last` carries over. A fresh clone has none: PA records the commit the target runs (the host's `HEAD` for `ha-config`, the last apply for `network-config`) with `--baseline`.

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
guarded = ["scripts/host-check.sh", "tests/deploy"]  # the repository's own extra paths (the fixed set is always added)
loaded = ["cloudflare/*.tf"]                # optional: ignored files the release would load (globs)
keep_env = ["CLOUDFLARE_API_TOKEN_READ_ALL"]  # optional: variables the release command needs
```

`checks_app` (the App slug of the required check runs, usually `github-actions`) is required with `check-runs` and refused with `workflow-runs`. Every key is validated; a missing or malformed one stops the gate with its name.

**What PA is shown (finding K6).** The candidate commit supplies these settings, so it cannot also decide alone what PA sees. The gate always guards a fixed set: `dev`, `.gitignore`, `harness.toml`, `.harness` (or the workshop's `harness`), `mise.toml`, `mise.lock`, `.github`, `.githooks`, `.claude`, `.codex`, `.agents`, and the release command. It adds the union of `guarded` at the last release and in the candidate, and the last release's release command, so dropping a path from the list does not hide it. It reads the `[gate]` table of `harness.toml` at the last release too: a change of any key (`repo`, `merger`, `verb`, `release`, `ci`, `checks_app`, `required`, `guarded`, `loaded`, `keep_env`) is printed as `key: 'old' -> 'new'`, and a last release with no readable `[gate]` table (a repository's first release under the core) makes every setting new. Any of these needs PA's `yes` on the terminal. `guarded` therefore lists only what the fixed set misses: host scripts the release calls, the release's own tests.

### The release command

Called from the repository root as `<release> [args…]`, after every check and PA's confirmation, with:

- `GATE_SHA`: the commit to release (`HEAD`, the tip of `main`);
- `GATE_LAST`: the last released commit (always set: the gate refuses without one);
- `GATE_RECORD_DIR`: `<git common dir>/dev-<verb>/`, where it may keep its own state (Terraform's variables checksum, the SSH target);
- the variables of the strict re-run plus `keep_env`, and **no** `GH_TOKEN` and no `GIT_CONFIG_*` entries (they carry the bot token).

It validates its own arguments before reading any credential, reads its credentials behind a Keychain prompt, and confirms on `/dev/tty` if it needs to. Its exit code decides the record:

| Exit | Meaning | Record |
|---|---|---|
| 0 | released | `last` = `GATE_SHA`, and a line in `log` |
| 3 | passed, nothing released (a dry run such as `deploy --check`) | nothing |
| anything else | failed | a `failed-exit-<n>` line in `log`; `last` unchanged |

### The strict re-run

The release verb is handed from `harness/dev` to `harness/gate` before `dev`'s own `mise exec` re-run. Stage 1 finds mise only at `/opt/homebrew/bin`, `/usr/local/bin` or `~/.local/bin` (never `PATH`), sets a system `PATH`, drops every variable outside a named list and every exported function, and re-runs under `mise exec --locked`. Stage 2 is marked by an argument and refuses any variable outside the same named list plus what bash, macOS and mise add (`PWD`, `OLDPWD`, `SHLVL`, `_`, `__CF_USER_TEXT_ENCODING`, `__MISE_*`): a named list, not a deny list (finding F6 of session 04), so a mise `[env]` section or a hand-typed second stage is caught whatever it sets.

A name on the list is not enough (finding K10). Stage 2 also refuses:

- `GIT_CONFIG_*` entries other than exactly those `gh-token.sh` exports (computed from the script itself: the same keys and values, no more, no fewer), so another credential helper, URL rewrite or option cannot ride on the kept names;
- any variable the mise configuration sets (`mise env -D` must print nothing: `[env]`, `_.file`, `_.source`), and any `PATH` entry it adds outside the tools' own directories (`_.path`), from every file mise reads: the repository's, every parent directory's, the global configuration.

Stage 2 runs `harness/dev check` only after the GitHub checks and without the GitHub credential ('Order of a release'), so every tool of `harness.toml` must resolve under mise.

In an agent's sandbox, the git proxy lives in `GIT_CONFIG_PARAMETERS`, which the re-run drops: a release from an agent shell needs the sandbox off (tracker finding of session 04b). `./dev gate` keeps it and works inside the sandbox.

### Refusal cases and their tests

Each refusal is one line, `dev: refused: …`, exit 1. `tests/test_gate.py` has at least one test for each:

| Check | Refused when |
|---|---|
| Settings | no `[gate]` table; bad `repo`, `merger`, `verb`, `release` (missing, not executable, `..`, untracked, a symbolic link, git mode other than `100755`), `ci`, `checks_app`, `required` (empty or blank), `guarded`, `loaded`, `keep_env`; `gh` not in `tools`; an unknown key, a key given twice, a blank value or array item (`conf.awk`) |
| Re-run | the other release verb; a variable outside the named list in stage 2 (a hand-typed `--stage2`); `GIT_CONFIG_*` entries that are not exactly `gh-token.sh`'s; a variable or `PATH` entry added by a mise configuration (repository, parent directory, global) |
| Lock | another release or baseline change of this clone is running |
| 1. Tree | `git ls-files -v` fails; an `assume-unchanged` or `skip-worktree` entry; a modified or untracked file; an ignored file mise loads (`mise.local.toml`, `.tool-versions`, `.config/`); an ignored file matching `loaded` |
| Token | no `GH_TOKEN` |
| 2. Tip | `origin` cannot be fetched (or the fetch passes the deadline); `HEAD` is not `origin/main`; GitHub's `main` differs or cannot be read |
| 3. CI | runs cannot be read; no run; a run not completed; a run neither green, neutral nor skipped, on any page; a required run missing, or from another App |
| 4. Merged by | PRs cannot be read; not the merge commit of a PR into `main`; several PRs; merged by anyone but `merger`; the PR cannot be read |
| 5. Since the last release | no record, a malformed one, or one whose commit is not in the clone (the refusal names `./dev gate --baseline <sha>`); `HEAD` does not descend from it; a first-parent commit after it that is not the merge commit of one PR into `main` merged by `merger` (a direct push, finding K21) |
| 6. Guarded diff | a path of the fixed set, of either `guarded` list or either release command changed, or a `[gate]` setting changed, and no terminal; PA does not type `yes` |
| Check | `./dev check` fails (run after check 6, without the GitHub credential) |
| Release | the release command fails (logged, not recorded); `last` changed during the run (not overwritten) |
| Baseline | no terminal; the commit is unknown or not on `origin/main`; PA does not type `yes` |

The unit tests replace GitHub with a `gh` shell function that answers from files (pages and a hung call included): they test the gate's decisions, not `gh`'s `--jq` filters, which are unchanged from the two live gates where they were tested against GitHub. The end-to-end tests run the normal entry point (`./dev deploy`) through both stages with the real mise and a fake `gh` that mise resolves (a fake tool install in a private mise data directory): they check the order of a release (every GitHub read before any repository code, `./dev check` and the release command without the token), the environment refusals, and the record. The re-run and end-to-end tests are skipped where mise is not in a fixed location.

### Moving a live repository to it (sessions 26 and 27)

`dev.conf` becomes the `[gate]` table; `scripts/` gets the release command, cut from the repository's `./dev` (`run_apply` and the `tfvars` checks for `network-config`; `read_target`, `release_deploy` and the host-`HEAD` check for `ha-config`, with `--check` exiting 3). The record directories keep their names (`dev-apply`, `dev-deploy`), so the last released commit carries over. The first release under the core finds no `[gate]` table at that commit, so PA confirms every setting as new along with the diff of the fixed set. Each live repository's `.githooks/` copies are deleted (the core hooks replace them), its `guarded` list keeps only paths outside the fixed set, and in `ha-config` nothing (the house host included) may push to `main` any more (check 5 refuses any first-parent commit that is not a PA merge).

## Guard

`harness/guard` is the one pre-tool-use hook of the core, for Claude Code, Codex and Antigravity (report 2.2, 'Hooks'). It reads the shell command an agent is about to run and denies:

| When | What | Why |
|---|---|---|
| Always | a push to `main` or `master`; a push of every branch (`--all`, `--mirror`, a bare `:`) or of a wildcard refspec (`refs/heads/*:…`); a force push (`--force`, `-f`, `--force-with-lease`, `--force-if-includes`, `+refspec`, a short-flag cluster holding `f` such as `-fu`); a remote branch deletion (`--delete`, `-d`, `:branch`, `--prune`); git's abbreviations of those long options (`--forc`, `--del`); a skipped git hook (`--no-verify` on any git command, `git commit -n`, `-c core.hooksPath=` or `--config-env=core.hooksPath=` on any git command); a git alias defined on the command line (`-c alias.…`) | PA merges; the git hooks run `./dev check` |
| Always | `gh pr merge` and `gh pr ready`, with any flags before the group or the verb (`gh -R o/r pr merge 5`, `gh pr -R o/r merge 5`; the same holds for `gh release` and `gh api` below); the REST merge endpoint; the GraphQL mutations `mergePullRequest`, `markPullRequestReadyForReview` and `enablePullRequestAutoMerge` anywhere in a command | PA merges and marks PRs ready (session 24, K2) |
| Always | `gh release create` (or `new`) without `--draft`/`-d`; `--draft=false` (or `0`, `f`) on `gh release create` or `edit`; a `gh api` write to a `releases` path (a POST, PATCH or PUT, or any field) without `draft=true`, or with `draft=false` | releases stay drafts until PA publishes them; with immutability on, a published release is permanent (K8) |
| Always | a local branch deleted by force: `git branch -D`, a short-flag cluster holding `D`, or a delete flag with a force flag in any order (`-d -f`, `-df`, `--delete --force`, `--force -d`, abbreviations); `git branch -d`, `-m`, `-M`, `-f` alone and `--list` pass | nothing checks that a force-deleted branch was merged; `/dev-delete-merged-branches` deletes only what GitHub shows merged at the local tip (24g I2, 24f F2) |
| Where nobody answers a prompt | `./dev apply`, `./dev deploy` (quoted, through a path, `mise exec`, `gh-token.sh` or `bash -c` too) and `gate release` / `gate --stage2` | the release confirms on the terminal and prompts in the Keychain |

"Where nobody answers a prompt" means: a Claude Code cloud session (`CLAUDE_CODE_REMOTE=true`); a permission mode other than `default`, `acceptEdits`, `plan` or `auto` (`bypassPermissions`, where session 12 saw an `ask` rule not prompt; `dontAsk`; a missing mode); and Antigravity, whose payload carries no mode. Everything else passes: the guard is not a permission system, and the repository's own rules and hooks (the connector guards of `ha-config`, for instance) stay beside it.

**Messages.** Each denial names the sanctioned way in the same line (24i's refusal rule): a `/dev-` command (`/dev-status` for a PR to merge, `/dev-delete-merged-branches`, `/dev-run-ci-locally` for a skipped hook, `/dev-check-release-readiness` for a release verb, `/dev-plugin-release` or `/dev-run-with-owner-token` to publish) or a command in backticks (the bot's push and draft PR, with the token script's path as the agent sees it: `harness/gh-token.sh` in the workshop, `.harness/gh-token.sh` in a consumer; `./dev setup` for a guard that cannot run). `tests/test_guard.py` checks every denial for one. A refusal is final: the agent runs what it names, or tells PA.

It fails closed: no `jq`, a payload it cannot read, a judged command that is present but not a string (an array, a number), a command longer than 200,000 bytes, a split that jq did not finish, or an unknown agent denies the call. It uses bash 3.2 builtins and `jq` only (`/usr/bin/jq` ships with macOS; CI runners have it) and writes no temporary file (until session 24b a here-document did, and an unwritable temporary folder let every command through).

**Time.** The agents let a call through when its hook runs past the timeout (10 s in the bindings), so the guard must stay well under it on any command. Bash 3.2's `${var//…}` is quadratic (8 s for a 6 KB command in a UTF-8 locale) and so are jq's regex functions on a long string (31 s for 190 KB), so the guard uses neither on the whole command: jq builds both views below one character at a time (`explode` and `foreach`), passes on only the simple commands that name `git`, `gh`, `dev`, `gate` or a PullRequest mutation, and bash judges those. Measured on a Mac: 0.07 s for 6 KB, 0.4 s for 50 KB, 1.5 s for 190 KB; `tests/test_guard.py` holds a 180 KB case to under 5 s. Longer commands are refused: split them.

Commands are matched as text, in two views, and a denial in either denies:

- **Flat.** A line ending in a backslash is joined to the next, `$'…'`/`$"…"` markers, `"` and `'` quotes and backslashes are removed, and every `;`, `&`, `|` and newline starts a new simple command. So `"git" push origin 'main'`, `\git push …`, `HEAD:ma""in` and `HEAD:$'main'` read as plain words, and a quoted command (`bash -c 'git push origin main'`) is judged as code.
- **Quote-aware** (Codex second read of 24b, C5). Only an unquoted `;`, `&`, `|` or newline starts a new simple command; quotes are removed and the blanks inside a quoted or escaped argument are kept as a non-blank byte, so the argument stays one word. So a quoted separator does not cut a command in two (`git -C '/tmp/a;b' push origin HEAD:main` is denied), and text inside an argument is not an option (`gh release create v1 --notes 'use --draft'` is not a draft and is denied). Escapes are not decoded (`$'\x6d'` stays as written).

So a commit message that quotes a denied command is denied too (flat view): reword it, or put a test payload in a file. Each view's simple commands are judged on their own, so a release creation is denied when either view finds it without a draft flag. One gap remains: inside a nested shell the quote-aware view sees one quoted word and the flat view sees the notes' text as words, so `bash -c 'gh release create v1 --notes "x --draft"'` passes.

What it cannot see, by design (it reads text, not the shell's evaluation):

- a bare `git push` (or `git push origin HEAD`) while the checked-out branch is `main`: the destination comes from the branch and its upstream, not the text (the core's `pre-push` hook refuses it, 'Git hooks', where `./dev setup` installed the hooks);
- variables, command substitutions and `${IFS}` tricks (`b=main; git push origin HEAD:$b`), and git or shell aliases, functions or `push.default`/`remote.*.push` settings defined elsewhere (config files, the environment, `GIT_CONFIG_*`);
- interpreters and scripts: `python3 -c`, `node -e`, a script file, `make`, a GraphQL query read from a file (`-f query=@file`), `curl` to the REST API;
- other GitHub REST writes to `main` (`/merges`, `/contents`, `/git/refs`): branch protection holds them in the workshop; in the live repositories the gate refuses to release past any commit on `main` that is not a PR merged by PA (check 5, since session 24c);
- tools other than the shell (the matchers are `Bash` and `run_command`).

Early warning, not the boundary (report 2.3): an agent with a shell can edit the guard or its bindings, and a hook that cannot start (missing file, not executable) lets the call through in all three agents.

### Bindings

Templates in `harness/bindings/`, copied to the repository root by `./dev sync` where the root file is absent (see 'Sync'). They call `.harness/guard`, the synced location; this repository's own copies call `harness/guard`, and `tests/test_guard.py` checks that the two agree.

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

Session 24c changed it (finding K24, PA's yes to the interface change):

- `--read-only` requests every permission the installation holds at level read; the gate's call is `gh-token.sh claude --read-only -- ./dev <verb>`. Read back with `--read-only --info`.
- Printing a token needs `--print`; `gh-token.sh <app>` alone prints the usage and exits 2. A printed token is the caller's and is never revoked by the script.
- In `--info` and `-- CMD` modes an exit trap, set right after the token is minted, revokes it on any exit: the end of the command, an error of the script, Ctrl-C or `TERM`. The command's exit status is kept.
- Every API request times out after 30 seconds.
- Owner mode (`pa -- CMD`) exports PA's token to the command and everything it starts, for as long as they run; nothing narrows or revokes it, so the command must be one named operation, never a shell or a tool that runs other code (`harness/gh-token.md`).

`ha-config`'s copy (`scripts/gh-token.sh`) keeps the old interface until session 27 replaces it with the core's.

## Agent files

`AGENTS.md` is canonical and stays under 24,000 bytes (Antigravity's limit; Codex allows 32 KiB). It holds a short shared block between `harness:shared:begin` and `harness:shared:end`, the same text in every repository, then the repository's own rules; depth goes into skills. `CLAUDE.md` is `@AGENTS.md` plus Claude-only notes. Claude Code reads `AGENTS.md` alone when there is no `CLAUDE.md`, but the stub stays. Templates for the block, the stub and the symlink command: `harness/templates/`.

Repository skills live in `.agents/skills/<name>/`. Claude Code does not load that folder directly; it loads it through `.claude/skills`, one committed directory symlink to `../.agents/skills`.

**Probe** (the first entry of the workaround register; re-run it to see whether the symlink can go). In a throwaway project holding one `SKILL.md` under `.agents/skills/<name>/`, run `claude -p "ok" --model haiku --output-format stream-json --verbose` and look for the name in the `skills` list of the `system`/`init` event. Result, 2026-11-17, macOS terminal: **absent** without the symlink, **listed** with it.

This repository has no skills of its own yet: its two helpers are slash commands in `.claude/commands/`, so `.agents/skills/` holds only a `.gitkeep`.

**Desktop app and cloud session** (2026-11-17, branch `kit-agent-files`, read-only prompt, Claude Code; version not shown by either surface). Both loaded `AGENTS.md` (the shared block) and the Claude-only section of `CLAUDE.md`; both listed `bump-plugin` and `new-plugin-skeleton` (shown as skills, not as commands); both showed `.claude/skills -> ../.agents/skills`; both refused `git push --dry-run origin HEAD:main` through the guard hook. The desktop app was tried in its local-session option (a local worktree, Code tab); its cloud-session option is the cloud result. Because the repository has no skills yet, the probe shows that the symlink survives checkout on both surfaces, not that a skill under `.agents/skills/` loads there; only the terminal probe (throwaway project) shows that. A guard refusal blocks the whole Bash call when the denied command is chained with others: run it alone.

## Path filters

`validate.yml` keeps one always-running core job, `Core checks` (`./dev ci`). A `changes` job lists the plugins whose files differ from the PR base, and each plugin's own job runs only when its path changed; pushes to `main` and manual runs check every plugin. On a PR, `Version bump` fails when a plugin's files changed and its version did not (`scripts/check-version-bump.py`). The required check, `Marketplace validation`, is an aggregate job that runs last, also after a failure, and passes only when the core checks and the filter succeeded and every other job succeeded or was skipped (session 24b, K4 and K5). See `docs/protected-main.md`. This replaces the PR check planner of the imported Python harness and the per-agent acceptance matrix, which the core does not carry.

## Spec tracking (`specs.lock`)

Report 2.7. This repository follows upstream specifications (Agent Skills, Agent Plugins, `AGENTS.md`, the marketplace formats of Claude Code and Codex, the rules and hooks pages of Codex and Antigravity). The old resolver (`spec-live`) fetched them on every run, so an upstream edit turned an unrelated PR red and left no record. `specs.lock` replaces it.

| File | Role |
|---|---|
| `tools/specs/watch.json` | The watch list: `git` sources (recorded by the commit their HEAD points to) and `pages` (recorded by the SHA-256 of the served bytes). Add or remove a source here, then run `./dev specs update`. |
| `specs.lock` | The committed record, one entry per watched source, sorted, no timestamp. |
| `tools/specs/specs.py` | `check` (offline) and `update` (online). Standard library only. |
| `.github/workflows/specs-bump.yml` | The weekly job (Mondays 06:17 UTC, or by hand): runs `update`; when the lock changed it pushes `specs-bump/<date>`, opens the PR and relies on the PR's own `pull_request` run for the required check (no write secret is stored, no dispatch). The job token (contents and pull-requests write) is held by the last step only: checkout keeps no credential (`persist-credentials: false`), `./dev setup` and `update` run without a token, and the last step refuses to push unless `git diff --name-only origin/main...HEAD` is exactly `specs.lock`, then pushes with the token as a one-command header (session 24b, K11). One bump PR at a time. A first PR by the bot waits for a maintainer's approval of that run: 'Bump PRs' in `protected-main.md`. Needs the repository setting that lets Actions create pull requests. |

- **`./dev specs check`** runs in `./dev check` and `./dev ci`, so in the pre-commit hook, in PR runs and on `main`. It validates the lock against the watch list: same names, same URLs, well-formed digests. It opens no socket (a unit test forbids it). It cannot go red because upstream moved.
- **`./dev specs update`** resolves every source and rewrites the lock if anything moved, printing what changed. It fails closed: if one source cannot be resolved, nothing is written. It reads no credential. Only the weekly job and a person run it.
- A page hash moves on any edit upstream, editorial ones included. The bump PR's diff names the source; reading the page says whether it matters. Pages that a script renders client-side hash their served shell, not their text; treat a source that never moves, or moves every week, as a defect of the watch list.
- `plugin.json` and marketplace entries are not validated against the locked schemas: the lock holds hashes, not contents. The checks of the plugins themselves stay in `scripts/validate-marketplace.py` and the path-filtered plugin jobs.

## Sync

`./dev sync <rev> <consumer-checkout> [--pr] [--keep-root <file>]…` runs in the workshop (a verb of this repository's `harness.toml`, `tools/sync/sync.py`, not part of the core). `<rev>` is a core tag (`harness-vX.Y`) or any commit-ish; it is resolved to a commit once, and every file is read from that commit, never from the working tree or the revision name again (so a tag that moves during the run cannot disagree with `VERSION`, Codex C6). `harness/core.files` lists what is core; since session 23b it names every tracked file under `harness/`, and nothing else reaches a consumer.

In the consumer, on a new branch `harness-sync/<rev>` and in one commit:

| What | Rule |
|---|---|
| `.harness/` | Replaced as a whole, byte for byte and mode for mode, with `VERSION` (revision and commit) and `CHECKSUMS` (one line per file: `<mode> <sha256> <path>`, mode `644` or `755`). Never merged or edited in place, so there is nothing to resolve. |
| `dev`, bindings (`.claude/settings.json`, `.codex/hooks.json`, `.agents/hooks.json`), `CLAUDE.md` | Written when the root file is absent; never overwritten. A root file that exists and differs leaves part of the core unwired (finding K22: the dispatcher for `dev`, the guard hook of that client for a binding), so the sync stops before writing anything, names each file and what would stay unwired, and exits 1, unless `--keep-root <file>` names it. A kept file is reported with the same consequence, in the commit and the PR body. |
| `AGENTS.md` shared block | Replaced between the `harness:shared` markers when both are present once; otherwise reported. |
| `.claude/skills` | Checked, reported, never changed. |
| `harness.toml`, `mise.toml`, `mise.lock` | The consumer's; never touched. |

The sync refuses a target that is not the top of a work tree, is the workshop, has uncommitted changes, already has the branch, has a differing root file not named by `--keep-root`, or already has this core ("nothing changed"; a failed run leaves no branch); and a `--keep-root` that names no root file of the core. Without `--pr` nothing leaves the machine; with it the branch is pushed and one PR is opened with `gh`, its body holding the report. Credentials are the caller's: an agent wraps the whole command in `harness/gh-token.sh`.

`./dev check` and `./dev ci` verify `.harness/CHECKSUMS` when `.harness/` exists: a changed or missing file, an executable bit that differs from the recorded mode, a symbolic link, or a file the list lacks, stops the run and names it. This detects an accident or a hand edit. It is not protection: an agent that can write `.harness/` can write `CHECKSUMS` too. The guard and review are what hold; the checksum makes drift visible. A consumer fixes drift by syncing again, never by editing `.harness/`. Tests: `tests/test_sync.py` (a disposable workshop and consumer; a one-byte change, an extra file, a symbolic link, a missing file and a changed mode are each caught; a differing root file is refused, kept with `--keep-root`, and a mistyped name refused; no git call names the revision after it is resolved).

## Workaround register and harness review

`docs/workaround-register.md` lists every workaround with its reason, exit condition and probe (`tools/probes/`); `tests/test_register.py` keeps it complete. The `harness-review` skill (`.agents/skills/harness-review/`) runs the probes and reads the pins, `specs.lock` and the agents' release notes twice a year, in two modes (workshop, consumer), and only proposes. `.github/workflows/harness-review-due.yml` opens the issue when a review is due.
