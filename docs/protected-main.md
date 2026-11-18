# Marketplace automation and protected main

`main` requires a pull request and the `Marketplace validation` check (the aggregate job of `validate.yml`), enforced for administrators; force pushes and deletion are off; the repository allows squash merges only. There is no automation that writes to `main`: a human merges every change, and no workflow holds a credential that can bypass the protection.

## Source map and contracts

| Source | Responsibility |
|---|---|
| `scripts/validate-marketplace.py` | Read-only structural check of both manifests against the plugin trees and the README table. No network. |
| `.github/workflows/validate.yml` | Five jobs and an aggregate. `Core checks` installs the pinned mise and tools, then runs `./dev ci` (unit tests, validator, shellcheck, actionlint: the checks listed in `harness.toml`). `Changed plugins` compares the PR with its base (`git diff`, no third-party action), and a plugin's own job (`Plugin checks (<name>)`) runs only when files under `plugins/<name>/` changed; pushes to `main` and manual runs check every plugin. `Version bump` (PRs only) runs `scripts/check-version-bump.py`: a PR that changes files under `plugins/<name>/` without changing that plugin's version fails, naming the plugin (see below). `Marketplace validation`, the required check on `main`, is the aggregate: it `needs:` every other job, runs also when one failed, and passes only when `Core checks` and `Changed plugins` succeeded and every other job succeeded or was skipped. Keep its display name aligned with branch protection, and add each new job to its `needs:` (`tests/test_workflows.py` fails otherwise). To add a plugin's checks, add an output to `changes`, a job gated on it, and the job to the aggregate's `needs:`. Organon's unit suite runs through `uv` (a dependency, locked by the plugin's `uv.lock`; `astral-sh/setup-uv` pinned by SHA, Linux only). Its own `scripts/dev check` assumes the plugin is the repository root and fails inside this repository, so it is not run; making it root-independent is a plugin change (session 25 decides). projectionlab and session-telemetry have no job: they hold a manifest and skill Markdown only, no code and no tests, and `./dev ci` already validates their manifests and README rows. Give them a job when one gains code or tests. |
| `scripts/check-version-bump.py` | The version-bump check (session 24, K5): merging a version bump is the release and PA's installs follow `main`, so a plugin change under an old number ships unreleased content. Compares each changed plugin's version at the merge base and at the head, reading the manifest the way `release-plugins.py` does (root `plugin.json` first). A new or removed plugin passes. No escape hatch: documentation and test changes inside a plugin carry a bump too. Locally: `python3 scripts/check-version-bump.py --base origin/main`. |
| `scripts/release-plugins.py` | Plans (and, outside `--dry-run`, creates) the `<plugin>/v<version>` tag and draft release for each plugin whose version changed, then builds the plugin's `.plugin` zip with `scripts/plugin_zip.py` and uploads it to the draft. |
| `.github/workflows/release.yml` | Runs `release-plugins.py` after a push to `main`, or by hand with `dry_run` on. |
| `tests/` | Disposable-repository tests for the release planning. They never touch real tags. |
| `AGENTS.md`, `CLAUDE.md` | Agent policy and project rules. |

The release procedure and the `stable` pin are in [releases.md](releases.md).

## Bump PRs (specs.lock)

`specs-bump.yml` opens the weekly PR with the job token, so GitHub treats `github-actions[bot]` as its author. The required check is the PR's own `pull_request` run of `Marketplace validation`; nothing dispatches it by hand.

- **First PR:** the repository's approval policy ('Require approval for first-time contributors') holds that run until a maintainer clicks 'Approve and run'; the merge box says 'Some checks are waiting for approval'. Seen on the first bump PR (session 22). A `workflow_dispatch` run on the branch does not clear it: a held run counts as unfinished.
- **Later PRs:** by the wording of that setting the hold ends once the bot has a PR merged here. The first bump PR was merged on 2026-11-17; the next one shows whether that holds. If it is held again, approving stays a weekly click.
- **Who merges:** a person, as for every PR. The job never merges.

## Why the release workflow is shaped this way

- **Trigger on a version change, not on every merge.** The script compares each plugin's `version` at the pushed commit with the one before the push. A merge that bumps nothing creates nothing, so the first run after any merge is safe.
- **A draft release, never a published one.** Release immutability, once enabled, makes a published release and its tag permanent, so the `.plugin` zips must be attached first. The workflow therefore attaches the zip to a draft and stops there; publishing is `gh release edit <tag> --draft=false`, after the assets are attached.
- **`contents: write` only in the release job.** The validation workflow stays read-only.
- **Reruns are safe.** A tag that already exists is skipped, so a failed run can be rerun.

## Maintenance and recovery

Change the script, its tests, this page and `releases.md` in one PR. For a workflow change run `./dev ci`, which includes `actionlint`. Tools come from `mise.toml`, never from the shell; see [harness-core.md](harness-core.md). Workflow files cannot be pushed by the bot Apps; PA releases that push.

If a release run fails halfway, read the log, fix the cause and rerun the workflow: tags already created are skipped. A wrong tag with no published release can be deleted (`git push origin :refs/tags/<tag>`) and the draft release deleted with `gh release delete`; a published release cannot be changed once immutability is on, so ship a new version instead. Do not force-push `main` or remove protection to recover.
