---
name: dev-harness-sync
description: Opens a pull request to sync the repository to a tagged harness core. Run when PA invokes /dev-harness-sync.
disable-model-invocation: true
---

# Sync a repository to a core tag

Use your own App name for `<bot>` (codex, claude or antigravity). Run from the repository root.

In a consumer, run `.harness/gh-token.sh <bot> -- .harness/harness-sync [<tag>] [--keep-root <file>]…`. Omit the tag to select the latest workshop tag. The script syncs a temporary checkout of origin/main and opens a PR.

In the workshop, get the consumer checkout and tag from PA’s request. For an omitted tag use `harness/harness-sync --latest`. Resolve the consumer’s GitHub repository from its origin, then run `harness/gh-token.sh <bot> --repo <consumer-owner/repo> -- ./dev sync <tag> <consumer-checkout> --pr`. The App needs access to that consumer.

In either mode, pass each explicit `--keep-root <file>` choice to the command. For example, `/dev-harness-sync --keep-root CLAUDE.md` preserves consumer notes on the latest-tag sync. If a differing root file was not named, relay the refusal so PA can review the file before choosing to preserve it.

Relay the sync report and PR link. Preserve the consumer script’s final `done:`, `left for PA:` and `next:` lines. In the workshop name the outcome, PA’s review and the next command from the report.
