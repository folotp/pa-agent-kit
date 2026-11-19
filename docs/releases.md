# Releases and the `stable` pin

## How a release happens

Merging a version bump is the release, in two steps: the merge, then PA's tag. Only PA can create a `*/v*` tag (session 25): a tag ruleset on `*/v*`, `harness-v*` and `stable` restricts creating, moving and deleting them, with the repository admin role as the only bypass. GitHub refuses the GitHub Actions App as a bypass actor on a personal repository, so the workflow cannot tag; it drafts the release of a tag PA pushes.

1. Bump the plugin's `version` in its `plugin.json` (`/bump-plugin <name> <version>` also updates the README table) and merge the PR (code-owner review: PA approves).
2. PA tags the bump commit with PA's own token, by running [`scripts/tag-release.py`](../scripts/tag-release.py) through the token wrapper (an agent may run it too; PA clicks Allow on the Keychain dialog for `github-owner-token`; `/dev-run-with-owner-token` holds this recipe):

   ```text
   harness/gh-token.sh owner -- python3 scripts/tag-release.py <plugin> --dry-run
   harness/gh-token.sh owner -- python3 scripts/tag-release.py <plugin>
   ```

   The script fetches, reads the plugin's version at `origin/main`, finds the commit that bumped it (the latest commit on `main` touching `plugins/<plugin>/`; it refuses when that commit did not change the version), refuses a tag that exists locally or on the remote, and pushes `<plugin>/v<version>` on that commit. It tags the bump commit, not the tip of `main`, so another plugin's merge in between does not move the tag. Without the wrapper the push is refused by the tag ruleset. By hand, the same thing is `git fetch origin && git tag <plugin>/v<version> <bump commit> && git push origin refs/tags/<plugin>/v<version>`.

   `python3 scripts/release-plugins.py --base <commit before the merge>` lists the tags a change calls for.
3. The push runs [`release.yml`](../.github/workflows/release.yml), job `release`. It opens a **draft** release on the tag, builds the plugin's `<name>-v<version>.plugin` zip and one `<skill>.zip` per skill from the tagged commit ([`scripts/plugin_zip.py`](../scripts/plugin_zip.py)) and uploads them. Check the assets (`gh release view <tag>`, `unzip -l`).
4. Publish: `gh release edit <plugin>/v<version> --draft=false`. With release immutability on, a published release and its tag can no longer change, which is why assets come first.

To preview what a merge calls for, start the workflow by hand from `main`: `gh workflow run release.yml --ref main -f base=<commit before the change>` (job `preview`: it prints the tags to push and creates nothing). To preview a branch, run the script locally: `python3 scripts/release-plugins.py --base <commit> --head <branch>`. To check a tag before pushing it: `python3 scripts/release-plugins.py --tag <plugin>/v<version> --head <commit> --dry-run`.

The `release` job is the only one with a write token, and it refuses before its script runs (session 24b, K8, and the Codex second read, C1; reshaped in session 25):

- it starts only for a pushed tag, never for a branch or a dispatch;
- the tagged commit must be on `origin/main`: the job runs the checked-out `release-plugins.py` with a contents-write token, so a tag on an unmerged commit would run unreviewed code with it;
- the script refuses a tag that is not `<plugin>/v<version>`, whose plugin is not in the marketplace manifest, or whose version differs from the plugin's `plugin.json` at the tagged commit, and a tag whose release is already published.

Agents create releases as drafts only: the guard denies `gh release create` without `--draft`, `--draft=false` and a `gh api` release write without `draft=true` (`docs/harness-core.md`, 'Guard'). Tagging and publishing (steps 2 and 4) are PA's.

### The `.plugin` zips

The zip carries a plugin's payload with the plugin root at the archive root; it is how skills are loaded by hand in the Gemini app. Selection: the plugin's `config/package-files.json` when it exists (an allowlist of files and directories), otherwise every tracked file; development configuration (`.claude`, `.codex`, `.agents`, `.github`, `tests`) never ships. It is built from a git revision, not the working tree, so local files cannot leak in. Entries are sorted with fixed timestamps, so two builds of one commit give the same bytes on the same Python and zlib (across other zlib versions the compressed bytes may differ while the contents stay the same).

The Gemini app accepts skills, not plugins (tested 2026-11-17: it refused a `.plugin`), so the release also gets one `<skill>.zip` per skill, with `SKILL.md` at the zip root. Build them with `--skills`.

Build locally, any plugin and revision: `python3 scripts/plugin_zip.py --ref HEAD --out dist --list organon` (no names builds all four). If the upload step fails in a release run, the draft stays without some or all of its assets: rerun the failed job (the draft is reused and its assets replaced), or build the zips with the command above at the tagged commit and `gh release upload --clobber <tag> <file>`. Design and recovery notes: [protected-main.md](protected-main.md).

## Pin your own installs to `stable`

Installs follow the default branch unless you pin them. `stable` is a moving tag that PA points at a commit PA has checked; installs that use it change only when the tag moves.

Create or move the tag (it has no release, so it is not immutable). PA runs this, in PA's own terminal: the guard denies the force push to an agent, and the tag ruleset of session 25 refuses it to the bots:

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
