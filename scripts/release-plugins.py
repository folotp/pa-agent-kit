#!/usr/bin/env python3
"""Draft the GitHub release for a plugin tag PA pushed, or preview which tags a merge calls for.

Merging a version bump is the release, in two parts. PA tags the merge commit
`<plugin>/v<version>` by hand (the tag ruleset of session 25 lets only PA create
`*/v*` tags: the GitHub Actions App cannot be a bypass actor on a personal
repository). Pushing the tag runs `release.yml`, which calls this script with
`--tag`: it opens a DRAFT GitHub release on the existing tag, builds the plugin's
`.plugin` zip and one zip per skill from the tagged commit (scripts/plugin_zip.py)
and uploads them. This script never creates or moves a tag and never publishes:
repository release immutability makes a published release and its tag permanent,
so publish with `gh release edit <tag> --draft=false` only after checking the assets.

Two modes:
  --tag <plugin>/v<version> [--head <sha>] [--dry-run]
      Validate the tag against the tagged commit: the plugin is listed in the
      marketplace manifest and its plugin.json there has exactly that version.
      Then create the draft (or reuse an existing DRAFT of that tag, replacing its
      assets) and upload. A tag whose release is already published is refused.
      `--dry-run` prints the plan and changes nothing. Needs `gh` credentials
      (`contents: write`) unless dry-run.
  --base <commit> [--head <rev>]
      Preview only: list the tags a merge calls for, that is the plugins whose
      version differs from the one at `--base` and whose tag does not exist yet.
      Changes nothing; no base (or all zeros) lists nothing.

Exit status is nonzero on a malformed manifest or version, a tag that does not
match its commit, or a failed build or upload. Stdlib only.

Failure behavior: a failure after the draft exists leaves the draft with some or
none of its assets; rerun the workflow job (the draft is reused and its assets
replaced) before publishing.
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


def release_for_tag(repo: Path, tag: str, head: str) -> Release:
    """Return the Release a pushed tag stands for, or raise ValueError.

    The tag must be `<plugin>/v<version>`, name a plugin the manifest lists at `head`,
    and match the version in that plugin's manifest at `head`: a tag that disagrees
    with the commit it points at would attach the wrong content to a permanent release."""
    plugin, sep, rest = tag.partition("/v")
    if not sep or not plugin or "/" in plugin or not SEMVER.match(rest):
        raise ValueError(f"tag {tag!r} is not <plugin>/v<version>")
    manifest = json.loads(git("show", f"{head}:{MARKETPLACE}", repo=repo))
    listed = {e.get("name"): e.get("source") for e in manifest.get("plugins", [])}
    source = listed.get(plugin)
    if not isinstance(source, str) or not source.startswith("./plugins/"):
        raise ValueError(f"tag {tag!r}: {plugin!r} is not a plugin of this marketplace")
    actual = version_at(repo, head, source[2:])
    if actual != rest:
        raise ValueError(f"tag {tag!r} names version {rest} but {source[2:]} is at {actual!r} in {head}")
    return Release(plugin, rest)


def release_state(repo: Path, tag: str) -> str | None:
    """Return "draft" or "published" for the release of `tag`, or None when it has none."""
    result = subprocess.run(["gh", "release", "view", tag, "--json", "isDraft"],
                            cwd=repo, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    return "draft" if json.loads(result.stdout)["isDraft"] else "published"


def draft_release(repo: Path, release: Release, sha: str) -> None:
    """Open (or reuse) the draft release of the existing tag and attach its zips.

    The zips are built from `sha`, the tagged commit. A draft left by a failed run is
    reused and its assets replaced; a published release is never touched."""
    state = release_state(repo, release.tag)
    if state == "published":
        raise RuntimeError(f"{release.tag} is already published: nothing to draft")
    if state is None:
        subprocess.run(
            ["gh", "release", "create", release.tag, "--draft", "--verify-tag",
             "--title", f"{release.plugin} {release.version}", "--generate-notes"],
            cwd=repo, check=True)
    with tempfile.TemporaryDirectory(prefix="plugin-zip-") as temp:
        assets = [plugin_zip.build(repo, sha, release.plugin, Path(temp))]
        assets += plugin_zip.build_skills(repo, sha, release.plugin, Path(temp))
        subprocess.run(["gh", "release", "upload", release.tag, "--clobber", *map(str, assets)],
                       cwd=repo, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", help="draft the release of this existing tag (<plugin>/v<version>)")
    parser.add_argument("--base", help="preview the tags a change since this commit calls for")
    parser.add_argument("--head", default="HEAD", help="commit being released or previewed (default HEAD)")
    parser.add_argument("--dry-run", action="store_true", help="with --tag: print the plan; change nothing")
    args = parser.parse_args()
    if bool(args.tag) == bool(args.base):
        parser.error("give exactly one of --tag and --base")
    try:
        if args.tag:
            release = release_for_tag(REPO_ROOT, args.tag, args.head)
            sha = git("rev-parse", f"{args.head}^{{commit}}").strip()
            print(f"release-plugins: {'would draft' if args.dry_run else 'drafting'} {release.tag} at {sha[:12]}")
            if not args.dry_run:
                draft_release(REPO_ROOT, release, sha)
            return 0
        base = args.base if not set(args.base) <= {"0"} else None
        releases = plan_releases(REPO_ROOT, base, args.head)
    except (ValueError, RuntimeError, plugin_zip.PackageError, subprocess.CalledProcessError) as exc:
        print(f"release-plugins: FAIL: {exc}")
        return 1
    if not releases:
        print("release-plugins: no version change, no tag to push")
    for release in releases:
        print(f"release-plugins: push tag {release.tag} (PA, on the merge commit)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
