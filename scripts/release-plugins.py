#!/usr/bin/env python3
"""Tag `<plugin>/v<version>` for every plugin whose version changed on main.

Merging a version bump is the release. For each plugin the Claude Code
manifest lists by relative path, this script compares the version in
plugin.json at `--base` with the version at `--head` (default HEAD). A plugin
is released when:
  - its version differs from the base version, or the plugin is new, and
  - the tag `<plugin>/v<version>` does not already exist.
An unchanged version never produces a tag, so the first run after a merge that
does not bump anything is a no-op.

A release is a tag plus a DRAFT GitHub release. The draft is deliberate:
repository release immutability makes a published release and its tag
permanent, so assets must be attached before it is published. After creating
each draft this script builds that plugin's `.plugin` zip from the tagged
commit (scripts/plugin_zip.py) and uploads it to the draft. This script never
publishes; publish with `gh release edit <tag> --draft=false` once you have
checked the assets.

`--dry-run` prints the plan and changes nothing (no tag, no release, no
network). Without it the script needs `git push` rights and `gh` credentials
(`contents: write`). Exit status is nonzero on a malformed manifest or version.
Stdlib only.

Failure behavior: tags are created and pushed one plugin at a time; a failure
stops the run, and a rerun picks up the remaining plugins because already
existing tags are skipped.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Sibling module; add the directory explicitly so importing this file by path (tests) works.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import plugin_zip  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = ".claude-plugin/marketplace.json"
SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
MANIFEST_NAMES = ("plugin.json", ".claude-plugin/plugin.json")


@dataclass(frozen=True)
class Release:
    """One planned release: the plugin, its new version and the tag to create."""
    plugin: str
    version: str

    @property
    def tag(self) -> str:
        return f"{self.plugin}/v{self.version}"


def git(*args: str, repo: Path = REPO_ROOT) -> str:
    """Run git in `repo`; raise with git's message on failure."""
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def version_at(repo: Path, rev: str, plugin_path: str) -> str | None:
    """Return the plugin's version at `rev`, or None if it has no manifest there."""
    for name in MANIFEST_NAMES:
        try:
            raw = git("show", f"{rev}:{plugin_path}/{name}", repo=repo)
        except RuntimeError:
            continue
        return json.loads(raw).get("version")
    return None


def plan_releases(repo: Path, base: str | None, head: str) -> list[Release]:
    """Return the releases to create for the plugins listed at `head`.

    With no `base` (a first run or a missing base commit) nothing is released:
    a release must be triggered by an observed version change."""
    if not base:
        return []
    manifest = json.loads(git("show", f"{head}:{MARKETPLACE}", repo=repo))
    existing = set(git("tag", "--list", repo=repo).split())
    releases = []
    for entry in manifest.get("plugins", []):
        source = entry.get("source")
        if not isinstance(source, str) or not source.startswith("./plugins/"):
            raise ValueError(f"{entry.get('name')}: source must be a relative plugin path")
        path = source[2:]
        new = version_at(repo, head, path)
        if not new or not SEMVER.match(new):
            raise ValueError(f"{entry.get('name')}: invalid version {new!r} at {head}")
        if new == version_at(repo, base, path):
            continue
        release = Release(entry["name"], new)
        if release.tag not in existing:
            releases.append(release)
    return releases


def publish_plan(repo: Path, releases: list[Release], head: str) -> None:
    """Create and push each tag at `head`, open its draft release, attach its zip.

    The zip is built from the tagged commit and uploaded to the draft; if the
    build or upload fails the draft stays without its asset and the run fails,
    so a later publish cannot happen unnoticed (the rerun skips the existing tag:
    attach the asset by hand with `scripts/plugin_zip.py` and `gh release upload`)."""
    sha = git("rev-parse", head, repo=repo).strip()
    for release in releases:
        git("tag", release.tag, sha, repo=repo)
        git("push", "origin", f"refs/tags/{release.tag}", repo=repo)
        subprocess.run(
            ["gh", "release", "create", release.tag, "--draft", "--verify-tag",
             "--title", f"{release.plugin} {release.version}", "--generate-notes"],
            cwd=repo, check=True)
        with tempfile.TemporaryDirectory(prefix="plugin-zip-") as temp:
            archive = plugin_zip.build(repo, sha, release.plugin, Path(temp))
            subprocess.run(["gh", "release", "upload", release.tag, str(archive)],
                           cwd=repo, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="commit before the merge; no base means no release")
    parser.add_argument("--head", default="HEAD", help="commit being released (default HEAD)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan; change nothing")
    args = parser.parse_args()
    base = args.base if args.base and not set(args.base) <= {"0"} else None
    try:
        releases = plan_releases(REPO_ROOT, base, args.head)
    except (ValueError, RuntimeError) as exc:
        print(f"release-plugins: FAIL: {exc}")
        return 1
    if not releases:
        print("release-plugins: no version change, nothing to tag")
        return 0
    for release in releases:
        print(f"release-plugins: {'would tag' if args.dry_run else 'tagging'} {release.tag}")
    if not args.dry_run:
        try:
            publish_plan(REPO_ROOT, releases, args.head)
        except (plugin_zip.PackageError, subprocess.CalledProcessError) as exc:
            print(f"release-plugins: FAIL: {exc}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
