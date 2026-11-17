# Releases and the `stable` pin

## How a release happens

Merging a version bump is the release.

1. Bump the plugin's `version` in its `plugin.json` (`/bump-plugin <name> <version>` also updates the README table) and merge the PR.
2. [`release.yml`](../.github/workflows/release.yml) runs on the push to `main`. For each plugin whose version differs from the one before the push, it tags `<plugin>/v<version>` on the merge commit and opens a **draft** release. A merge that bumps nothing creates nothing.
3. Attach the assets (the `.plugin` zips, once the packaging exists) to the draft.
4. Publish: `gh release edit <plugin>/v<version> --draft=false`. With release immutability on, a published release and its tag can no longer change, which is why assets come first.

To preview what a run would do, start the workflow by hand: `gh workflow run release.yml -f base=<commit before the change>`. `dry_run` is on by default and prints the plan without creating a tag or release. Locally: `python3 scripts/release-plugins.py --base <commit> --dry-run`.

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
