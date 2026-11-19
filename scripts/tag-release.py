#!/usr/bin/env python3
"""Tag the merge commit of a plugin's version bump, so `release.yml` drafts its release.

Merging a version bump is the release in two parts (docs/releases.md): PA pushes
`<plugin>/v<version>` on the merge commit, then the workflow drafts the release. This
script is PA's half, replacing the hand-typed `git fetch && git tag && git push`. Only PA
can create a `*/v*` tag (tag ruleset, session 25), so run it under PA's token:

    harness/gh-token.sh owner -- python3 scripts/tag-release.py <plugin>

What it does, in order, and where it stops:
  1. fetches `<remote>` (default `origin`), branch `main` and tags: read-only;
  2. reads the plugin's version at `<remote>/main` and finds the bump commit, the latest
     commit on `main` (first parent) that touched `plugins/<plugin>/`; that commit must be
     the one that changed the version (a later content change without a bump is refused:
     it ships new content under an old number, K5);
  3. refuses unless the plugin is listed in the marketplace manifest, the version is
     semver and the tag is free, locally and on the remote (`release_for_tag` of
     release-plugins.py, so it applies the same rules the workflow applies);
  4. pushes the tag on the bump commit, without creating a local tag. `--dry-run` stops
     before the push and changes nothing.

It tags the bump commit itself, not `main`'s tip, so another plugin's merge in between
cannot move the tag. It never publishes: after the workflow drafts the release, check the
assets and publish by hand (`gh release edit <tag> --draft=false`). A published release and
its tag are permanent (release immutability), so the dry run is worth reading.

Exit status: 0 tagged (or dry run ok), 1 refused or failed. Stdlib only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
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


def plan_tag(repo: Path, plugin: str, rev: str, remote_tags: set[str]) -> tuple[str, str]:
    """Return (tag, commit) for the plugin's version at `rev`, or raise ValueError.

    `remote_tags` are the tag names that already exist on the remote: git cannot see them
    until fetched, and a tag created there since would make the push fail late.
    The commit is the latest first-parent commit of `rev` touching the plugin; it must have
    changed the plugin's version relative to its parent."""
    manifest = json.loads(git("show", f"{rev}:{release_plugins.MARKETPLACE}", repo=repo))
    source = {e.get("name"): e.get("source") for e in manifest.get("plugins", [])}.get(plugin)
    if not isinstance(source, str) or not source.startswith("./plugins/"):
        raise ValueError(f"{plugin!r} is not a plugin of this marketplace")
    path = source[2:]
    version = version_at(repo, rev, path)
    if not version:
        raise ValueError(f"{path} has no manifest version at {rev}")
    tag = f"{plugin}/v{version}"
    commit = git("log", "-1", "--first-parent", "--format=%H", rev, "--", path, repo=repo).strip()
    if not commit:
        raise ValueError(f"no commit on {rev} touches {path}")
    if version_at(repo, commit, path) == version_at(repo, f"{commit}^", path):
        raise ValueError(
            f"the latest commit touching {path} ({commit[:12]}) did not change its version "
            f"({version}): bump the version in a PR and merge it before tagging")
    # Same rules as the workflow: manifest listing, semver, version at the commit, and a
    # local tag of this name must already point at the commit.
    release_plugins.release_for_tag(repo, tag, commit)
    if tag in remote_tags or git("tag", "--list", tag, repo=repo).strip():
        raise ValueError(f"tag {tag} already exists: a release is never retagged (immutability)")
    return tag, commit


def remote_tag_names(repo: Path, remote: str) -> set[str]:
    """Return the names of the tags on `remote`, annotated-tag peel lines dropped."""
    out = git("ls-remote", "--tags", remote, repo=repo)
    names = set()
    for line in out.splitlines():
        ref = line.split("\t", 1)[-1]
        if ref.startswith("refs/tags/") and not ref.endswith("^{}"):
            names.add(ref[len("refs/tags/"):])
    return names


def main(argv: list[str] | None = None, repo: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("plugin", help="plugin name, as listed in the marketplace manifest")
    parser.add_argument("--remote", default="origin", help="remote holding main (default origin)")
    parser.add_argument("--dry-run", action="store_true", help="print the tag and commit; push nothing")
    args = parser.parse_args(argv)
    try:
        git("fetch", "--quiet", "--tags", args.remote, repo=repo)
        tag, commit = plan_tag(repo, args.plugin, f"{args.remote}/main", remote_tag_names(repo, args.remote))
        print(f"tag-release: {'would push' if args.dry_run else 'pushing'} {tag} on {commit[:12]}: "
              f"{git('log', '-1', '--format=%s', commit, repo=repo).strip()}")
        if not args.dry_run:
            git("push", args.remote, f"{commit}:refs/tags/{tag}", repo=repo)
            print(f"tag-release: pushed {tag}; the Release workflow now drafts it "
                  f"(check the assets, then publish by hand)")
    except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"tag-release: FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
