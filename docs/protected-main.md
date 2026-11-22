# Marketplace automation and protected main

`main` requires a pull request and the `Marketplace validation` check (the aggregate job of `validate.yml`), enforced for administrators; force pushes and deletion are off; the repository allows squash merges only. There is no automation that writes to `main`: a human merges every change, and no workflow holds a credential that can bypass the protection.

**Code owners.** `.github/CODEOWNERS` names PA (`* @folotp`) for every path. Session 25 recorded activation of required code-owner review with one approval and dismissal of stale approvals. PA reviews and merges through the protected branch workflow.

**Dependabot.** `.github/dependabot.yml` updates the SHA-pinned GitHub Actions only: monthly, one grouped PR, releases at least 7 days old (report 2.8). Its PRs pass the same required check as any other. The file has the same settings as the core template `harness/templates/dependabot.yml` (a test keeps them equal), which `./dev sync` writes into a consumer that has none; the core check `harness/check-dependabot` (run by `./dev check` and `./dev ci`) requires a `github-actions` entry with a cooldown of 7 days or more that covers every local action calling a remote one. **Pins.** Every `uses:` in `.github/workflows/` names a full 40-character commit SHA (a local `./` action or a `docker://` image digest excepted), because a tag or branch can be moved to other code; the core check `harness/check-pins` (run by `./dev check` and `./dev ci`; tested by `PinnedActionsTest` in `tests/test_workflows.py`) fails on any other reference, in workflows and in local actions (`.github/actions/**/action.yml`), with the version in a trailing comment (`# v7.0.1`) for Dependabot. The repository setting 'Require actions to be pinned to a full-length commit SHA' (Settings, Actions, General; PA sets it) makes GitHub refuse such a job at run time as well.

## Source map and contracts

| Source | Responsibility |
|---|---|
| `scripts/validate-marketplace.py` | Read-only structural check of both manifests against the plugin trees and the README table. No network. |
| `.github/workflows/validate.yml` | Five jobs and an aggregate. `Core checks` installs the pinned mise and tools, then runs `./dev ci` (unit tests, validator, shellcheck, actionlint: the checks listed in `harness.toml`). `Changed plugins` compares the PR with its base (`git diff`, no third-party action), and a plugin's own job (`Plugin checks (<name>)`) runs only when files under `plugins/<name>/` changed; pushes to `main` and manual runs check every plugin. `Version bump` (PRs only) runs `scripts/check-version-bump.py`: a PR that changes files under `plugins/<name>/` without changing that plugin's version fails, naming the plugin (see below). `Marketplace validation`, the required check on `main`, is the aggregate: it `needs:` every other job, runs also when one failed (`if: always()`), and passes only when `Core checks` and `Changed plugins` succeeded and every other job succeeded or was skipped. Without `if: always()` GitHub would skip the aggregate after a failed plugin job, and branch protection counts a skipped required check as passing. Keep its display name aligned with branch protection, and add each new job to its `needs:` (`tests/test_workflows.py` fails otherwise; the same file runs the aggregate's jq rule on failed, cancelled and skipped results of every job it waits on). To add a plugin's checks, add an output to `changes`, a job gated on it, and the job to the aggregate's `needs:`. Organon's unit suite runs through `uv` (a dependency, locked by the plugin's `uv.lock`; `astral-sh/setup-uv` pinned by SHA, Linux only). Its own `scripts/dev check` assumes the plugin is the repository root and fails inside this repository, so it is not run; making it root-independent is a plugin change (session 25 decides). projectionlab and session-telemetry have no job: they hold a manifest and skill Markdown only, no code and no tests, and `./dev ci` already validates their manifests and README rows. Give them a job when one gains code or tests. |
| `scripts/check-version-bump.py` | The version-bump check (session 24, K5): merging a version bump is the release and PA's installs follow `main`, so a plugin change under an old number ships unreleased content. Compares each changed plugin's version at the merge base and at the head, reading the manifest the way `release-plugins.py` does (root `plugin.json` first). A new or removed plugin passes. No escape hatch: documentation and test changes inside a plugin carry a bump too. Locally: `python3 scripts/check-version-bump.py --base origin/main`. |
| `scripts/release-plugins.py` | `--tag`: checks a tag PA pushed against its commit, opens (or reuses) the draft release on it, builds the `.plugin` zip and the per-skill zips with `scripts/plugin_zip.py` and uploads them. `--base`: lists the tags a change calls for. It never creates a tag and never publishes. |
| `scripts/tag-release.py` | Pushes the reviewed version tag on the exact bump commit. Use `/dev-plugin-release` for the dry run and the owner-token command. |
| `.github/workflows/release.yml` | Job `release`: runs `release-plugins.py --tag` when PA pushes a `<plugin>/v<version>` tag whose commit is on `main`. Job `preview`: by hand from `main`, lists the tags a change calls for, with no write token (see `releases.md`). |
| `tests/` | Disposable-repository tests for the release planning. They never touch real tags. |
| `AGENTS.md`, `CLAUDE.md` | Agent policy and project rules. |

The release procedure and the `stable` pin are in [releases.md](releases.md).

## Bump PRs (specs.lock, mise pins)

`specs-bump.yml` opens the weekly PR with the job token, so GitHub treats `github-actions[bot]` as its author. `mise-bump.yml` does the same for the mise pins (`mise.toml`, `mise.lock`, `.mise/locks/`): a monthly PR from `mise-bump/<date>` and a weekly security PR from `mise-security/<date>`, at most one open per kind. A manual run (the workflow's `kind` input: `version` or `security`) uses the same path. The required check is the PR's own `pull_request` run of `Marketplace validation`; nothing dispatches it by hand.

- **First PR:** the repository's approval policy ('Require approval for first-time contributors') holds that run until a maintainer clicks 'Approve and run'; the merge box says 'Some checks are waiting for approval'. Seen on the first bump PR (session 22). A `workflow_dispatch` run on the branch does not clear it: a held run counts as unfinished.
- **Later PRs:** by the wording of that setting the hold ends once the bot has a PR merged here. The first bump PR was merged on 2026-11-17; the next one shows whether that holds. If it is held again, approving stays a weekly click.
- **Who merges:** a person, as for every PR. The job never merges.

## Why the release workflow is shaped this way

- **Trigger on a pushed version tag.** The workflow builds the plugin from the tagged commit, which must already be on `main`.
- **A draft release, never a published one.** Release immutability, once enabled, makes a published release and its tag permanent, so the `.plugin` zips must be attached first. The workflow therefore attaches the zips to a draft and stops there; use `/dev-plugin-release` to prepare publication once the assets are attached.
- **`contents: write` only in the release job.** The validation workflow stays read-only.
- **PA tags, the job drafts (session 25).** The tag ruleset lets only PA create `*/v*` tags, and GitHub refuses the GitHub Actions App as a bypass actor on a personal repository, so the job cannot tag. A pushed tag is also a deliberate act: a merge alone releases nothing. The cost is one tag push per release.
- **Reruns reuse the draft.** The release script finds the existing draft in the releases list and replaces its assets.

## Maintenance and recovery

Change the script, its tests, this page and `releases.md` in one PR. For a workflow change run `./dev ci`, which includes `actionlint`. Tools come from `mise.toml`, never from the shell; see [harness-core.md](harness-core.md). Use `/dev-run-with-owner-token` for a workflow-file push.

If a release run fails halfway, use `/dev-read-github-actions-log` to find the cause. After fixing it, use `/dev-run-with-owner-token` to rerun the failed job: the draft is reused and its assets replaced. For an incorrect tag with a draft, use `/dev-run-with-owner-token` to prepare each recovery operation: delete the draft, then delete the remote tag. For a published immutable release, ship a new version. Do not force-push `main` or remove protection to recover.
