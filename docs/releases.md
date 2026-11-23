# Releases and the `stable` pin

## How a release happens

Use /dev-help to find the workshop release command. Run `/dev-plugin-release <plugin>` in Claude Code or invoke the same skill by name in Codex or Antigravity. Run it again after each checkpoint.

1. Start a new bump with `/dev-plugin-release <plugin> patch` (or `minor` or `major`). The command plans the manifest and README bump. After explicit approval it opens a draft PR as the bot. PA reviews, marks it ready and merges it when checks pass. Use `/dev-status` to find the PR.
2. After the merge, `/dev-plugin-release <plugin>` dry-runs the tag plan against `origin/main`. It prints the exact invocation of [the tag script](../scripts/tag-release.py), pinned to the full bump commit SHA. After giving explicit go, PA runs that line in their terminal and chooses **Allow** once in the Keychain dialog for `github-owner-token`. The repository tag ruleset restricts creation of `*/v*`, `harness-v*` and `stable` tags.
3. The pushed tag starts the [release workflow](../.github/workflows/release.yml). It opens a draft, builds the plugin archive and one zip per skill from the tagged commit using [the packaging script](../scripts/plugin_zip.py), and attaches them.
4. `/dev-plugin-release <plugin>` checks for all expected uploaded assets and prints the publish command. After separate explicit approval, PA runs it in their terminal and chooses **Allow** once for `github-owner-token`. The command names the release by ID and includes `tag_name` explicitly, using `gh api -X PATCH repos/{owner}/{repo}/releases/<id> -f tag_name=<tag> -F draft=false`. Every draft edit supplies `tag_name` so GitHub keeps it associated with the correct tag.
5. `/dev-plugin-release <plugin>` confirms the release is published and immutable. Refresh with `/plugin marketplace update pa-marketplace` and then `/reload-plugins` in Claude Code, or run `codex plugin marketplace upgrade` in Codex.

Draft read-back uses the bot's normal token and the releases list or release ID. The `--read-only` token cannot see drafts. Use the release ID or list for drafts because the tag lookup endpoints, including `gh release view <tag>`, can omit them. [GitHub REST release endpoints](https://docs.github.com/en/rest/releases/releases#list-releases).

For a local preview, run `./dev x python3 scripts/release-plugins.py --base <commit> --head <branch>` to list tags, or `./dev x python3 scripts/release-plugins.py --tag <plugin>/v<version> --head <commit> --dry-run` to check a tag. The workflow's manual Preview job is available under Actions. For the owner-token procedure use `/dev-run-with-owner-token`.

The `release` job is the only one with a write token, and it refuses before its script runs (session 24b, K8, and the Codex second read, C1; reshaped in session 25):

- it starts only for a pushed tag, never for a branch or a dispatch;
- the tagged commit must be on `origin/main`: the job runs the checked-out `release-plugins.py` with a contents-write token, so a tag on an unmerged commit would run unreviewed code with it;
- the script refuses a tag that is not `<plugin>/v<version>`, whose plugin is not in the marketplace manifest, or whose version differs from the plugin's `plugin.json` at the tagged commit, and a tag whose release is already published.

Agents create releases as drafts only: the guard denies `gh release create` without `--draft`, `--draft=false` and a `gh api` release write without `draft=true` (`docs/harness-core.md`, 'Guard'). For steps 2 and 4 use `/dev-plugin-release`.

### The `.plugin` zips

The zip carries a plugin's payload with the plugin root at the archive root; it is how skills are loaded by hand in the Gemini app. Selection: the plugin's `config/package-files.json` when it exists (an allowlist of files and directories), otherwise every tracked file; development configuration (`.claude`, `.codex`, `.agents`, `.github`, `tests`) never ships. It is built from a git revision, not the working tree, so local files cannot leak in. Entries are sorted with fixed timestamps, so two builds of one commit give the same bytes on the same Python and zlib (across other zlib versions the compressed bytes may differ while the contents stay the same).

The Gemini app accepts skills, not plugins (tested 2026-11-17: it refused a `.plugin`), so the release also gets one `<skill>.zip` per skill, with `SKILL.md` at the zip root. Build them with `--skills`.

Build locally, any plugin and revision: `./dev x python3 scripts/plugin_zip.py --ref HEAD --out dist --list organon` (no names builds all four). If the upload step fails in a release run, the draft stays without some or all of its assets: rerun the failed job (the draft is reused and its assets replaced), or build the zips with the command above at the tagged commit and `gh release upload --clobber <tag> <file>`. Design and recovery notes: [protected-main.md](protected-main.md).

## Pin your own installs to `stable`

Installs follow the default branch unless you pin them. `stable` is a moving tag that PA points at a commit PA has checked; installs that use it change only when the tag moves.

Create or move the tag (it has no release, so it is not immutable). Use `/dev-run-with-owner-token` to prepare the owner-token step. PA runs this in their terminal: the guard denies the force push to an agent, and the tag ruleset of session 25 refuses it to the bots:

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
