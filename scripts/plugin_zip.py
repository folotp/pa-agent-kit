#!/usr/bin/env python3
"""Build one reproducible `<name>-v<version>.plugin` zip per plugin.

The `.plugin` zip is how a plugin's skills reach hosts that import files by
hand (the Gemini app). It is the same payload the Claude Code install gets,
packed as a zip with the plugin root at the archive root.

Inputs come from a git revision (default HEAD), never from the working tree,
so stray local files cannot leak in and two builds of one commit agree.

Selection, per plugin directory `plugins/<dir>`:
  - If `<dir>/config/package-files.json` exists, it is the allowlist: a JSON
    array of files or directories (relative to the plugin root). A listed path
    that does not exist at the revision is an error.
  - Otherwise every tracked file ships.
  In both cases development configuration (`.claude`, `.codex`, `.agents`,
  `.github`, `.git`, `tests`) and local noise (`.DS_Store`, `__pycache__`,
  `*.pyc`, `*.bak`, `*.plugin`, `*.skill`) are dropped.

Symlinks are stored as regular files holding their target's content (zip
symlinks are not portable); a link that leaves the plugin tree is an error.

Reproducibility: entries are sorted, timestamps are fixed to 1980-01-01, and
modes are normalised to 0644/0755 (executable bit from git). The bytes also
depend on the zlib build that compresses them, so equality is guaranteed for
the same Python and zlib; across machines with different zlib versions, compare
the file lists and contents (`unzip -l`) instead.

Usage:
  scripts/plugin_zip.py [--ref REV] [--out DIR] [--list] [PLUGIN ...]
Without plugin names every plugin in .claude-plugin/marketplace.json is built.
Failure behavior: any malformed manifest, missing allowlist entry or escaping
symlink exits nonzero before anything is written for that plugin.
Stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = ".claude-plugin/marketplace.json"
MANIFEST_NAMES = ("plugin.json", ".claude-plugin/plugin.json")
ALLOWLIST = "config/package-files.json"
DEV_DIRS = {".claude", ".codex", ".agents", ".github", ".git", "tests", "__pycache__"}
NOISE_SUFFIXES = (".pyc", ".bak", ".plugin", ".skill")
NOISE_NAMES = {".DS_Store"}
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


class PackageError(Exception):
    """A plugin cannot be packaged; the message says which input is wrong."""


def git(repo: Path, *args: str) -> bytes:
    """Run git in `repo` and return stdout; raise PackageError with git's message."""
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)
    if result.returncode != 0:
        raise PackageError(f"git {' '.join(args)} failed: {result.stderr.decode().strip()}")
    return result.stdout


def tree_entries(repo: Path, rev: str, prefix: str) -> dict[str, tuple[str, str]]:
    """Map path (relative to `prefix`) to (mode, blob sha) for every tracked file under it."""
    out = git(repo, "ls-tree", "-r", "-z", rev, "--", prefix + "/")
    entries = {}
    for record in out.split(b"\0"):
        if not record:
            continue
        meta, path = record.decode().split("\t", 1)
        mode, _kind, sha = meta.split()
        entries[path[len(prefix) + 1:]] = (mode, sha)
    return entries


def is_excluded(rel: str) -> bool:
    parts = rel.split("/")
    return (bool(DEV_DIRS.intersection(parts[:-1])) or parts[-1] in NOISE_NAMES
            or parts[-1].endswith(NOISE_SUFFIXES))


def select(rel_paths: set[str], allowlist: list[str] | None) -> list[str]:
    """Return the sorted files to ship; raise if an allowlist entry matches nothing."""
    if allowlist is None:
        chosen = set(rel_paths)
    else:
        chosen = set()
        for entry in allowlist:
            entry = entry.rstrip("/")
            hits = {p for p in rel_paths if p == entry or p.startswith(entry + "/")}
            if not hits:
                raise PackageError(f"package-files.json lists {entry!r}, which does not exist")
            chosen |= hits
    return sorted(p for p in chosen if not is_excluded(p))


def read_blob(repo: Path, sha: str) -> bytes:
    return git(repo, "cat-file", "blob", sha)


def resolve_symlink(repo: Path, entries: dict[str, tuple[str, str]], rel: str) -> bytes:
    """Return the content a symlink at `rel` points to, following links inside the tree."""
    seen = set()
    current = rel
    while True:
        mode, sha = entries[current]
        if mode != "120000":
            return read_blob(repo, sha)
        if current in seen:
            raise PackageError(f"symlink loop at {rel}")
        seen.add(current)
        target = posixpath.normpath(posixpath.join(posixpath.dirname(current),
                                                   read_blob(repo, sha).decode()))
        if target.startswith("..") or target not in entries:
            raise PackageError(f"symlink {rel} points outside the plugin or to nothing")
        current = target


def marketplace_path(repo: Path, rev: str, name: str) -> str:
    """Return the repo-relative directory of plugin `name` from the marketplace at `rev`."""
    manifest = json.loads(git(repo, "show", f"{rev}:{MARKETPLACE}"))
    for entry in manifest.get("plugins", []):
        if entry.get("name") == name:
            source = entry.get("source")
            if not isinstance(source, str) or not source.startswith("./plugins/"):
                raise PackageError(f"{name}: source must be a relative plugin path")
            return source[2:]
    raise PackageError(f"{name}: not listed in {MARKETPLACE}")


def plugin_names(repo: Path, rev: str) -> list[str]:
    manifest = json.loads(git(repo, "show", f"{rev}:{MARKETPLACE}"))
    return [entry["name"] for entry in manifest.get("plugins", [])]


def build(repo: Path, rev: str, name: str, out_dir: Path) -> Path:
    """Write `<name>-v<version>.plugin` into `out_dir` from `rev` and return its path."""
    prefix = marketplace_path(repo, rev, name)
    entries = tree_entries(repo, rev, prefix)
    manifest_rel = next((m for m in MANIFEST_NAMES if m in entries), None)
    if manifest_rel is None:
        raise PackageError(f"{name}: no plugin.json at {rev}")
    manifest = json.loads(resolve_symlink(repo, entries, manifest_rel))
    version = manifest.get("version")
    if manifest.get("name") != name or not version:
        raise PackageError(f"{name}: plugin.json name/version do not match the marketplace")
    allowlist = None
    if ALLOWLIST in entries:
        allowlist = json.loads(resolve_symlink(repo, entries, ALLOWLIST))
        if not isinstance(allowlist, list) or not all(isinstance(a, str) for a in allowlist):
            raise PackageError(f"{name}: {ALLOWLIST} must be an array of strings")
    files = select(set(entries), allowlist)
    if not files:
        raise PackageError(f"{name}: nothing to package")
    payloads = {rel: resolve_symlink(repo, entries, rel) for rel in files}
    out_dir.mkdir(parents=True, exist_ok=True)
    archive_path = out_dir / f"{name}-v{version}.plugin"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for rel in files:
            info = zipfile.ZipInfo(rel, FIXED_TIME)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            executable = entries[rel][0] == "100755"
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            archive.writestr(info, payloads[rel], compresslevel=9)
    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("plugins", nargs="*", help="plugin names (default: all in the marketplace)")
    parser.add_argument("--ref", default="HEAD", help="git revision to package (default HEAD)")
    parser.add_argument("--out", default="dist", help="output directory (default dist)")
    parser.add_argument("--list", action="store_true", help="print each archive's files")
    args = parser.parse_args()
    try:
        for name in args.plugins or plugin_names(REPO_ROOT, args.ref):
            path = build(REPO_ROOT, args.ref, name, Path(args.out))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            print(f"{path}  sha256:{digest[:16]}")
            if args.list:
                with zipfile.ZipFile(path) as archive:
                    for member in archive.namelist():
                        print(f"  {member}")
    except (PackageError, json.JSONDecodeError) as exc:
        print(f"plugin-zip: FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
