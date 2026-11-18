# Releases and the `stable` pin

## How a release happens

Merging a version bump is the release.

1. Bump the plugin's `version` in its `plugin.json` (`/bump-plugin <name> <version>` also updates the README table) and merge the PR.
2. [`release.yml`](../.github/workflows/release.yml) runs on the push to `main`. For each plugin whose version differs from the one before the push, it tags `<plugin>/v<version>` on the merge commit and opens a **draft** release. A merge that bumps nothing creates nothing.
3. The same run builds the plugin's `<name>-v<version>.plugin` zip from the tagged commit ([`scripts/plugin_zip.py`](../scripts/plugin_zip.py)) and uploads it to the draft. Check the asset (`gh release view <tag>`, `unzip -l`).
4. Publish: `gh release edit <plugin>/v<version> --draft=false`. With release immutability on, a published release and its tag can no longer change, which is why assets come first.

To preview what a run on `main` would do, start the workflow by hand from `main`: `gh workflow run release.yml --ref main -f base=<commit before the change>`. `dry_run` is on by default and prints the plan without creating a tag or release. To preview a branch, run the script locally: `python3 scripts/release-plugins.py --base <commit> --head <branch> --dry-run`.

The workflow refuses before its script runs, in both modes (session 24b, K8, and the Codex second read, C1):

- when the run's ref is not `refs/heads/main` (the job does not even start: its `if:` names `main`) or its commit is not on `origin/main`. The job holds a contents-write token and runs the checked-out `release-plugins.py`, so a run from another branch, even a dry run, would execute that branch's unmerged code with the token;
- when `base` does not resolve to a commit: an unknown base would make every plugin look changed (a push with no previous commit, all zeros, releases nothing).

Agents create releases as drafts only: the guard denies `gh release create` without `--draft`, `--draft=false` and a `gh api` release write without `draft=true` (`docs/harness-core.md`, 'Guard'). Publishing (step 4) is PA's. Tags themselves are not yet ruled: session 25 adds a tag ruleset on `*/v*`, `harness-v*` and `stable` that restricts creating, moving and deleting them to PA.

### The `.plugin` zips

The zip carries a plugin's payload with the plugin root at the archive root; it is how skills are loaded by hand in the Gemini app. Selection: the plugin's `config/package-files.json` when it exists (an allowlist of files and directories), otherwise every tracked file; development configuration (`.claude`, `.codex`, `.agents`, `.github`, `tests`) never ships. It is built from a git revision, not the working tree, so local files cannot leak in. Entries are sorted with fixed timestamps, so two builds of one commit give the same bytes on the same Python and zlib (across other zlib versions the compressed bytes may differ while the contents stay the same).

The Gemini app accepts skills, not plugins (tested 2026-11-17: it refused a `.plugin`), so the release also gets one `<skill>.zip` per skill, with `SKILL.md` at the zip root. Build them with `--skills`.

Build locally, any plugin and revision: `python3 scripts/plugin_zip.py --ref HEAD --out dist --list organon` (no names builds all four). If the upload step fails in a release run, the draft stays without its asset: build the zip with the command above at the tagged commit and `gh release upload <tag> <file>`.

If a run fails halfway, rerun it: tags that already exist are skipped. Design and recovery notes: [protected-main.md](protected-main.md).

## Pin your own installs to `stable`

Installs follow the default branch unless you pin them. `stable` is a moving tag that PA points at a commit PA has checked; installs that use it change only when the tag moves.

Create or move the tag (it has no release, so it is not immutable). PA runs this, in PA's own terminal: the guard denies the force push to an agent, and the tag ruleset of session 25 will refuse it to the bots:

```text
git tag -f stable <commit> && git push -f origin refs/tags/stable
```

Claude Code:

```text
/plugin marketplace add folotp/pa-agent-kit@stable
/plugin install <plugin-name>@pa-marketplace
```

Codex:

```text
codex plugin marketplace add folotp/pa-agent-kit --ref stable
codex plugin add <plugin-name>@pa-marketplace
```

To move an existing install onto `stable`, remove the marketplace and add it again with the ref. To follow a moved tag later, run `/plugin marketplace update pa-marketplace` (Claude Code) or `codex plugin marketplace upgrade` (Codex). Only `organon` is listed for Codex.
