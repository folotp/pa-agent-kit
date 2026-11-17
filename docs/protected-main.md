# Marketplace automation and protected main

`main` requires a pull request and the `Marketplace validation` check, enforced for administrators; force pushes and deletion are off; the repository allows squash merges only. There is no automation that writes to `main`: a human merges every change, and no workflow holds a credential that can bypass the protection.

## Source map and contracts

| Source | Responsibility |
|---|---|
| `scripts/validate-marketplace.py` | Read-only structural check of both manifests against the plugin trees and the README table. No network. |
| `.github/workflows/validate.yml` | Installs the pinned mise and tools, then runs `./dev ci` (unit tests, validator, shellcheck, actionlint: the checks listed in `harness.toml`). Its job name, `Marketplace validation`, is the required check on `main`; keep the two aligned. The same file holds the path filters: a `changes` job compares the PR with its base (`git diff`, no third-party action) and a plugin's own job (`Plugin checks (<name>)`) runs only when files under `plugins/<name>/` changed; pushes to `main` and manual runs check every plugin. A skipped job passes branch protection, so only `Marketplace validation` is required. To add a plugin's checks, add an output to `changes` and a job gated on it. Organon's own suite needs `uv` and a macOS runner and is not wired yet (open question). |
| `scripts/release-plugins.py` | Plans (and, outside `--dry-run`, creates) the `<plugin>/v<version>` tag and draft release for each plugin whose version changed, then builds the plugin's `.plugin` zip with `scripts/plugin_zip.py` and uploads it to the draft. |
| `.github/workflows/release.yml` | Runs `release-plugins.py` after a push to `main`, or by hand with `dry_run` on. |
| `tests/` | Disposable-repository tests for the release planning. They never touch real tags. |
| `AGENTS.md`, `CLAUDE.md` | Agent policy and project rules. |

The release procedure and the `stable` pin are in [releases.md](releases.md).

## Why the release workflow is shaped this way

- **Trigger on a version change, not on every merge.** The script compares each plugin's `version` at the pushed commit with the one before the push. A merge that bumps nothing creates nothing, so the first run after any merge is safe.
- **A draft release, never a published one.** Release immutability, once enabled, makes a published release and its tag permanent, so the `.plugin` zips must be attached first. The workflow therefore attaches the zip to a draft and stops there; publishing is `gh release edit <tag> --draft=false`, after the assets are attached.
- **`contents: write` only in the release job.** The validation workflow stays read-only.
- **Reruns are safe.** A tag that already exists is skipped, so a failed run can be rerun.

## Maintenance and recovery

Change the script, its tests, this page and `releases.md` in one PR. For a workflow change run `./dev ci`, which includes `actionlint`. Tools come from `mise.toml`, never from the shell; see [harness-core.md](harness-core.md). Workflow files cannot be pushed by the bot Apps; PA releases that push.

If a release run fails halfway, read the log, fix the cause and rerun the workflow: tags already created are skipped. A wrong tag with no published release can be deleted (`git push origin :refs/tags/<tag>`) and the draft release deleted with `gh release delete`; a published release cannot be changed once immutability is on, so ship a new version instead. Do not force-push `main` or remove protection to recover.
