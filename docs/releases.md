# Releases and the `stable` pin

## How a release happens

Merging a version bump is the release.

1. Bump the plugin's `version` in its `plugin.json` (`/bump-plugin <name> <version>` also updates the README table) and merge the PR.
2. [`release.yml`](../.github/workflows/release.yml) runs on the push to `main`. For each plugin whose version differs from the one before the push, it tags `<plugin>/v<version>` on the merge commit and opens a **draft** release. A merge that bumps nothing creates nothing.
3. The same run builds the plugin's `<name>-v<version>.plugin` zip from the tagged commit ([`scripts/plugin_zip.py`](../scripts/plugin_zip.py)) and uploads it to the draft. Check the asset (`gh release view <tag>`, `unzip -l`).
4. Publish: `gh release edit <plugin>/v<version> --draft=false`. With release immutability on, a published release and its tag can no longer change, which is why assets come first.

To preview what a run would do, start the workflow by hand: `gh workflow run release.yml -f base=<commit before the change>`. `dry_run` is on by default and prints the plan without creating a tag or release. Locally: `python3 scripts/release-plugins.py --base <commit> --dry-run`.

### The `.plugin` zips

The zip carries a plugin's payload with the plugin root at the archive root; it is how skills are loaded by hand in the Gemini app. Selection: the plugin's `config/package-files.json` when it exists (an allowlist of files and directories), otherwise every tracked file; development configuration (`.claude`, `.codex`, `.agents`, `.github`, `tests`) never ships. It is built from a git revision, not the working tree, so local files cannot leak in. Entries are sorted with fixed timestamps, so two builds of one commit give the same bytes on the same Python and zlib (across other zlib versions the compressed bytes may differ while the contents stay the same).

Build locally, any plugin and revision: `python3 scripts/plugin_zip.py --ref HEAD --out dist --list organon` (no names builds all four). If the upload step fails in a release run, the draft stays without its asset: build the zip with the command above at the tagged commit and `gh release upload <tag> <file>`.

If a run fails halfway, rerun it: tags that already exist are skipped. Design and recovery notes: [protected-main.md](protected-main.md).

## Pin your own installs to `stable`

Installs follow the default branch unless you pin them. `stable` is a moving tag that PA points at a commit PA has checked; installs that use it change only when the tag moves.

Create or move the tag (it has no release, so it is not immutable):

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
