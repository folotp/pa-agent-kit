# Release infrastructure development

Read the repository [AGENTS.md](../../../AGENTS.md) first. It is the shared agent contract; root CLAUDE.md imports it. Code contracts live beside the implementation, architecture and recovery instructions live here, and the one authorized release procedure is [runbook.md](runbook.md). Keep all three consistent in the same PR.

## Source ownership and data flow

| Source | Role and boundary |
|---|---|
| `SKILL.md` | User-triggered entry: Claude dispatches a thin executor; other agents read the same runbook directly |
| `agents/plugin-release-executor.md` | Claude adapter; no independent copy of the release procedure |
| `scripts/release.py` | Portable deterministic operations: identity, extension selection, preflight, verified archive and receipt |
| `scripts/package.sh` | Low-level generic ZIP implementation; no release authorization or source-validation contract |
| `scripts/branch-guard.py` | Generic main/detached/pre-push guards for the release driver; the workshop's own guard is `harness/guard` |
| `tests/test_release.py` | Disposable extension/fallback fixtures, null/malformed configuration, literal braces and output propagation |
| `tests/test_branch_guard.py` | Main/detached commits and remote destination guards |
| `config/release.json` | This plugin's extension: preflight runs the unit tests, package builds the `.plugin` with the workshop's `scripts/plugin_zip.py` (run with the plugin root as working directory) |
| workshop `.github/workflows/validate.yml`, job `plugin-pa-toolkit` | Unit tests of this plugin on Linux when it changes; part of the required `Marketplace validation` check |

General orchestration stays here. Toolkit and Organon each own their allowlist and shared checks through repository extensions; marketplace owns its manifests, bot and validator. Do not hardcode a plugin identity/path into the generic driver or copy the runbook into another repository.

## Execution and receipt contracts

The CLI requires a clean selected repository and an explicit output directory/JSON receipt path. Root plugin.json is canonical when present; legacy .claude-plugin/plugin.json remains supported. The selected packager is resolved explicitly, defaulting to package.sh beside this driver, without scanning caches or guessing an installed version.

An existing `config/release.json` must be a version-1 object with nonempty string argv arrays `preflight` and `package`; invalid configuration fails instead of falling back. Only `{packager}` and `{output}` are substituted, in one pass. Python dictionaries, JSON, regex braces and unknown names remain literal; inserted path values are never rescanned. No shell interpolation occurs. The argv commands are trusted repository code and require review before execution.

Both dry-run and build run the same preflight/package commands and verify a real temporary archive. Only an absent extension chooses `git archive HEAD` into temporary staging followed by package.sh, excluding ignored and untracked source artifacts. The generic driver verifies one expected archive, ZIP integrity, safe entry paths and matching manifest identity; a repository extension supplies stricter inventory checks. Do not claim the generic fallback is a universal allowlist or a complete repository test suite.

| Receipt field | Meaning |
|---|---|
| `name`, `version` | Selected source/archive identity; must agree |
| `files` | ZIP entry count including directory entries; not a source-file count |
| `dry_run` | Whether a verified archive is discarded after checking |
| `archive` | Absolute retained path in build mode; null for dry-run |
| `planned_archive` | Proposed absolute destination in dry-run; never pass it to an uploader |

Temporary staging is cleaned on success/failure. A previous result receipt is removed before the invocation; success is written only after verification. Keep output/receipt paths outside source and carry the exact `archive` value to an authorized upload. The driver never commits, tags, pushes, publishes or edits marketplace manifests. Direct callers of `execute()` must establish the CLI's clean-tree prerequisite themselves.

## Tests, toolchain and CI

The generic release implementation remains Python 3.9+ standard library, with Git,
Bash, jq, zip, unzip and (for fallback extraction) tar. Consumer repositories define
their additional gates through the generic extension, never inside this driver.

This plugin is developed in the workshop. Run `./dev check` from the workshop root before
committing and `./dev ci` before pushing (`./dev setup` installs the pinned tools). The tests
themselves are:

```sh
python3 -B -m unittest discover -s tests -v
```

run from `plugins/pa-toolkit/`, which is also what the `plugin-pa-toolkit` job runs on Linux.
The required context is the workshop's single `Marketplace validation`; it fails when this job
fails, and a change under `plugins/pa-toolkit/` also needs a version bump. The standalone
toolkit repository's `Release checks (ubuntu-latest)` / `(macos-latest)` contexts, its
`scripts/dev` and its `release-checks.yml` no longer exist for this plugin. Workflow permissions
are read-only; the release itself is the workshop's tag-triggered `release.yml`.

Add focused behavioral regressions when changing a contract: extension and fallback, dry-run and build, failure propagation and receipt/path handling. Run the actual selected repository's dry-run from a clean worktree for cross-repository integration. Do not dispatch a marketplace bump or publish a test release to verify the driver. Optional Claude compatibility validation is distinct from portable mandatory tests; legacy Claude skill fields are not assumed valid under an unrelated portable schema.

## Branch guards and recovery

Install local guards from a stable selected checkout:

```sh
python3 /path/to/pa-toolkit/skills/plugin-release/scripts/branch-guard.py install
```

Run this in the target repository. The installer honors Git's hook location, which linked worktrees may share. It checks both hook destinations before writing and preserves unmanaged files. pre-commit rejects main/detached HEAD; pre-push reads Git's four-field stdin records and rejects a main destination even when the source is a feature branch. The marked launcher points to this script's absolute path: reinstall from a stable checkout before removing or moving its old source. Organon's stronger staged-snapshot hook must be preserved, not replaced.

If validation fails, fix source or dependency access and rerun the required command; do not skip gates or reuse a stale receipt. A new extension schema needs an explicit compatibility decision and regressions, not an implicit fallback. After functional driver/packager changes merge, consumers adopt the merged commit pin through their own PR/CI; comment-only documentation updates need no automatic repin. Restore a previous reviewed pin through the same process if rollback is needed.

## Cross-repository release sequence

Follow [the shared runbook](runbook.md): bump/changelog on a release branch, tests and PR, exact merged remote-main identity, repeat required gates for that commit, verified retained archive/receipt, then explicitly authorized tag and publication. Never push directly to protected main. Marketplace follows its separately validated bump PR, with no automatic bypass or merge.

Current source edits do not update installed plugin copies. Use an explicit checkout for development, and distribute an authorized release separately. Organon's [architecture guide](https://github.com/folotp/organon-plugin/blob/main/docs/development-architecture.md) explains its specific staged/CI/package layers; marketplace's [automation guide](https://github.com/folotp/pa-marketplace/blob/main/docs/protected-main.md) owns bot dispatch and recovery.
