#!/usr/bin/env python3
"""Fail when a plugin's files change without a version bump.

Merging a version bump is the release (docs/releases.md), and PA's installs follow
`main`: a change under `plugins/<name>/` that keeps the old version ships new content
under an old number, which is how organon and pa-toolkit drifted past their tags
(session 24, K5). For each plugin directory with a changed file between the merge
base of `--base` and `--head`, this check compares the plugin's version at the two
points and fails when it did not change. There is no escape hatch: a plugin change,
documentation and tests included, carries a bump.

Not judged here: a plugin that is new (no manifest at the merge base) or removed
(no manifest at head) passes; whether the new version is valid semver and its tag
is free is release-plugins.py's job at release time. The manifest lookup (root
`plugin.json`, then `.claude-plugin/plugin.json`) is release-plugins.py's
`version_at`, imported so that both read a version the same way.

Usage: check-version-bump.py --base <rev> [--head <rev>]   (CI passes the PR's base SHA)
Exit codes: 0 every changed plugin is bumped, 1 a plugin is not bumped,
2 the revisions cannot be read. Stdlib only, no network.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_SPEC = importlib.util.spec_from_file_location("release_plugins", Path(__file__).resolve().parent / "release-plugins.py")
release_plugins = importlib.util.module_from_spec(_SPEC)
# @dataclass in that module resolves its module through sys.modules.
sys.modules[_SPEC.name] = release_plugins
_SPEC.loader.exec_module(release_plugins)
git = release_plugins.git
version_at = release_plugins.version_at


def changed_plugins(repo: Path, merge_base: str, head: str) -> list[str]:
    """Return the `plugins/<name>` directories with a changed file, sorted.

    `-z` gives raw, NUL-separated paths: without it git quotes a name holding a non-ASCII
    character, a tab or a newline (`"plugins/a/\\303\\251.md"`), and the plugin directory would
    read as `"plugins/a`, which has no manifest, so the plugin would pass unbumped (Codex C2).
    `--no-renames` lists a moved file under both its old and its new path: with rename
    detection only the new path shows, and a file moved out of a plugin would not count as a
    change to it (Codex C3).
    """
    out = git("diff", "--name-only", "--no-renames", "-z", merge_base, head, "--", "plugins/", repo=repo)
    names = [name for name in out.split("\0") if name]
    return sorted({"/".join(name.split("/")[:2]) for name in names if name.count("/") >= 2})


def unbumped(repo: Path, base: str, head: str) -> list[tuple[str, str]]:
    """Return (plugin path, version) for each changed plugin whose version did not change."""
    merge_base = git("merge-base", base, head, repo=repo).strip()
    missing = []
    for path in changed_plugins(repo, merge_base, head):
        old, new = version_at(repo, merge_base, path), version_at(repo, head, path)
        if old is not None and new is not None and old == new:
            missing.append((path, new))
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="the PR's base commit (or branch)")
    parser.add_argument("--head", default="HEAD", help="the commit to check (default HEAD)")
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        missing = unbumped(args.repo, args.base, args.head)
    except (RuntimeError, ValueError) as error:
        print(f"check-version-bump: FAIL: {error}", file=sys.stderr)
        return 2
    for path, version in missing:
        print(
            f"check-version-bump: FAIL: {path} changed but its version is still {version}: "
            f"bump it in its plugin.json in this PR, then use /dev-plugin-release after merge",
            file=sys.stderr,
        )
    if missing:
        return 1
    print("check-version-bump: every changed plugin carries a version bump")
    return 0


if __name__ == "__main__":
    sys.exit(main())
