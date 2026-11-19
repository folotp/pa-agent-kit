# The harness core in this repository

`.harness/` is the harness core, copied byte for byte from the workshop (`folotp/pa-agent-kit`, its `harness/` folder) at the tag named in `.harness/VERSION`. Never edit a file here: `./dev check` compares every file with `.harness/CHECKSUMS` and refuses any change. To update it, run `/dev-harness-sync` (it opens a sync PR as the bot); PA merges. The full contract is the workshop's `docs/harness-core.md` at that tag: `https://github.com/folotp/pa-agent-kit/blob/<tag>/docs/harness-core.md`.

`/dev-help` lists every command for PA and for agents. Each one ends with `done:`, `left for PA:` and `next:` lines.

## Verbs (`./dev`)

| Verb | What it does |
|---|---|
| `setup` | Installs the pinned tools of `mise.toml` and the core's git hooks. Once per clone, in PA's own terminal (the agent sandbox cannot write `.git/config`). |
| `check` | Tools under mise, `.harness/` against its checksums, the git hooks, the core checks below, then the repository's own offline `check`. Before every commit. |
| `ci` | The same, then every check of `harness.toml`'s `[checks]`, in order. Before every push; CI runs it too. |
| `update-local-repo` | Brings the main checkout's `main` up to GitHub's (fetch, fast-forward only), runs `setup`, prunes merged branches (with a bot token), and says when the agent must restart. Refuses, changing nothing, on uncommitted files or local commits GitHub lacks. `/dev-update-local-repo` runs it as your bot. |
| `gate`, `apply` / `deploy` | The release gate, in a repository with a `[gate]` table (`/dev-check-release-readiness`). |
| `x <command…>` | Any command under the pinned tools. |
| `<verb>` | The repository's own verbs, from `harness.toml`'s `[verbs]`. |

## Core checks (`./dev check` and `./dev ci`)

- **Pins** (`check-pins`): every `uses:` in `.github/workflows/` and `.github/actions/**/action.yml` names a full 40-character commit SHA, with the version in a comment (`@<sha> # v7.0.1`); a local `./` action and a digest-pinned `docker://` image pass.
- **Dependabot** (`check-dependabot`): with workflows, `.github/dependabot.yml` has a `github-actions` entry with `cooldown: default-days:` of 7 or more, and lists every local action that calls a remote one under `directories` (for example `"/"` and `"/.github/actions/*"`). Schedule, groups and prefix are the repository's.
- **Skill links** (`skill-links`) verifies discovery links against the synced skill directories and reports missing, conflicting or retired links.
- **Guard bindings** (`check-bindings`): `.claude/settings.json`, `.codex/hooks.json` and `.agents/hooks.json` each call `.harness/guard`. A repository with its own file merges the `PreToolUse` entry of `.harness/bindings/<file>` into it; until then the check fails on purpose, because the agent would otherwise run without the guard.

## What the sync writes, and what it leaves to the repository

- Replaced as a whole: `.harness/`. Replaced between its markers: the shared block of `AGENTS.md`.
- Written only when absent, then the repository's own: `dev`, the three binding files, `CLAUDE.md` (first line `@AGENTS.md`), `AGENTS.md` (`.harness/templates/AGENTS.md`), `.github/dependabot.yml` (`.harness/templates/dependabot.yml`). A differing `dev`, binding or `CLAUDE.md` stops the sync unless kept on purpose.
- Never written, only reported: a CI workflow. `.harness/templates/ci.yml` is the skeleton (pinned mise, `./dev setup`, `./dev ci`); copying it is PA's push, because a bot cannot push a workflow file.
- Never touched: `harness.toml`, `mise.toml`, `mise.lock`.

## Guard and tokens

The guard (`.harness/guard`) refuses PA's actions (merge, ready, push to `main`, force push, published release, skipped hooks, `git branch -D`) and names the sanctioned way in the same line. A refusal is final: run what it names, or tell PA. Agents act on GitHub as their bot through `.harness/gh-token.sh <bot> -- …`; PA's own token is released one command at a time with `owner -- …`: see `.harness/gh-token.md`. Merged branches are deleted with `/dev-delete-merged-branches` (`.harness/git-prune-merged.sh`: only when GitHub shows the merge at the local tip); a repository's standing branches go in `harness.toml` as `protected_branches = ["…"]`, and the script never deletes them, nor `main` or `master`.

## Cloud sessions

A cloud session has no mise: `./dev` stops with `mise not found` and installs nothing. Install mise with its official installer (it lands in `~/.local/bin`, where `./dev` looks), then run `./dev setup`.

## CI lessons

- A workflow that calls the Claude action must fail its job when the action's result says `is_error: true`: the action itself can end green after an error (a credit or a permission failure), and the review is then silently missing.
- One required check per repository: with several jobs, a final job with `if: always()` and `needs:` every other job fails unless each succeeded (see the comment in `.harness/templates/ci.yml`).

## Harness review

The twice-yearly harness review (probes of the agents, pins, specs) runs in the workshop, not here. Report a workaround or a broken pointer to PA, who carries it there.
