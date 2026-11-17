#!/usr/bin/env python3
"""specs.lock: the committed record of the upstream specifications this repository follows.

Two verbs, run through `./dev specs <verb>` (harness.toml, [verbs]):

  check    Offline. Validates `specs.lock` against `tools/specs/watch.json`. It opens no socket, so
           local, PR and `main` checks give one result for one commit, whatever upstream does.
  update   Online. Re-resolves every watched source, rewrites `specs.lock` when something moved and
           prints what changed (Markdown, usable as a PR body). Fails closed: if any source cannot be
           resolved, nothing is written. Only the weekly job and a person run it.

Watch list (watch.json): `git` sources are recorded by the commit their HEAD points to, `pages` by
the SHA-256 of the bytes served at the URL (redirects followed, HTTPS only). A page hash moves on
any upstream edit, including editorial ones: the bump PR's diff and the page itself say whether it
matters. Standard library only; no credential is read or sent.

Lock layout (sorted, two-space JSON, no timestamp, so an unchanged upstream gives an unchanged file):
  {"schema_version": 1, "sources": {"<name>": {"kind": "git", "url": ..., "revision": <40 hex>}
                                               | {"kind": "page", "url": ..., "sha256": <64 hex>}}}
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent.parent
WATCH = ROOT / "tools" / "specs" / "watch.json"
LOCK = ROOT / "specs.lock"

GIT_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+\.git")
HTTPS_URL = re.compile(r"https://[^\s\"'<>]+")
SHA1 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
NAME = re.compile(r"[a-z][a-z0-9-]*")
MAX_PAGE_BYTES = 16 * 1024 * 1024
TIMEOUT_SECONDS = 45


class SpecsError(Exception):
    """A watch list, a lock or an upstream answer that cannot be accepted."""


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SpecsError(f"{path}: {error}") from error


def load_watch(path=WATCH):
    """Return {name: (kind, url)}. Names are unique across both groups; anything odd is refused."""
    data = load_json(path)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise SpecsError(f"{path}: schema_version must be 1")
    if set(data) != {"schema_version", "git", "pages"}:
        raise SpecsError(f"{path}: keys must be schema_version, git, pages")
    watch = {}
    for group, kind, url_ok in (("git", "git", GIT_URL), ("pages", "page", HTTPS_URL)):
        if not isinstance(data[group], dict):
            raise SpecsError(f"{path}: {group} must be an object")
        for name, url in data[group].items():
            if not NAME.fullmatch(name):
                raise SpecsError(f"{path}: bad source name {name!r}")
            if name in watch:
                raise SpecsError(f"{path}: duplicate source name {name!r}")
            if not isinstance(url, str) or not url_ok.fullmatch(url):
                raise SpecsError(f"{path}: {name}: unacceptable {kind} URL")
            watch[name] = (kind, url)
    if not watch:
        raise SpecsError(f"{path}: the watch list is empty")
    return watch


def validate_lock(lock, watch):
    """Return a list of problems (empty when the lock is sound). Pure: no I/O, no network."""
    if not isinstance(lock, dict) or set(lock) != {"schema_version", "sources"}:
        return ["lock: keys must be schema_version and sources"]
    problems = []
    if lock["schema_version"] != 1:
        problems.append("lock: schema_version must be 1")
    sources = lock["sources"]
    if not isinstance(sources, dict):
        return problems + ["lock: sources must be an object"]
    for name in sorted(set(watch) - set(sources)):
        problems.append(f"{name}: watched but not in the lock (run ./dev specs update)")
    for name in sorted(set(sources) - set(watch)):
        problems.append(f"{name}: in the lock but no longer watched (run ./dev specs update)")
    for name in sorted(set(watch) & set(sources)):
        kind, url = watch[name]
        entry = sources[name]
        field, pattern = ("revision", SHA1) if kind == "git" else ("sha256", SHA256)
        if not isinstance(entry, dict) or set(entry) != {"kind", "url", field}:
            problems.append(f"{name}: entry must have exactly kind, url, {field}")
        elif entry["kind"] != kind:
            problems.append(f"{name}: kind is {entry['kind']!r}, the watch list says {kind!r}")
        elif entry["url"] != url:
            problems.append(f"{name}: url differs from the watch list (run ./dev specs update)")
        elif not isinstance(entry[field], str) or not pattern.fullmatch(entry[field]):
            problems.append(f"{name}: {field} is not a lowercase hex digest of the right length")
    return problems


def check(watch_path=WATCH, lock_path=LOCK):
    """The offline verb. Returns a process exit code."""
    try:
        watch = load_watch(watch_path)
        problems = validate_lock(load_json(lock_path), watch)
    except SpecsError as error:
        problems = [str(error)]
    for problem in problems:
        print(f"specs: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"specs: lock matches the watch list ({len(watch)} sources); nothing contacted")
    return 0


def git_revision(url):
    """The commit the remote HEAD points to; anything but exactly one answer fails."""
    out = subprocess.run(
        ["git", "ls-remote", url, "HEAD"],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        check=False,
        # No prompt for credentials: the sources are public.
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "GIT_TERMINAL_PROMPT": "0"},
    )
    lines = out.stdout.splitlines()
    if out.returncode != 0 or len(lines) != 1 or not re.fullmatch(r"[0-9a-f]{40}\tHEAD", lines[0]):
        raise SpecsError(f"cannot resolve HEAD of {url}: {out.stderr.strip() or out.stdout.strip()}")
    return lines[0].split("\t")[0]


def page_sha256(url):
    """SHA-256 of the response body. HTTPS only (redirects included); bounded size."""

    class HttpsOnly(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not newurl.startswith("https://"):
                raise SpecsError(f"{url}: redirect to a non-HTTPS address refused")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(HttpsOnly)
    request = urllib.request.Request(url, headers={"User-Agent": "specs-lock/1"})
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_PAGE_BYTES + 1)
    except (OSError, ValueError) as error:
        raise SpecsError(f"cannot fetch {url}: {error}") from error
    if not body or len(body) > MAX_PAGE_BYTES:
        raise SpecsError(f"{url}: empty or over {MAX_PAGE_BYTES} bytes")
    return hashlib.sha256(body).hexdigest()


def resolve(watch, git=git_revision, page=page_sha256):
    """Resolve every watched source; one failure raises, so no partial lock exists."""

    def one(item):
        name, (kind, url) = item
        if kind == "git":
            return name, {"kind": "git", "url": url, "revision": git(url)}
        return name, {"kind": "page", "url": url, "sha256": page(url)}

    with ThreadPoolExecutor(max_workers=4) as pool:
        resolved = dict(pool.map(one, sorted(watch.items())))
    return {"schema_version": 1, "sources": resolved}


def render(lock):
    return json.dumps(lock, indent=2, sort_keys=True) + "\n"


def describe_changes(old, new):
    """Markdown list of what moved between two locks; empty string when nothing did."""
    old_sources = (old or {}).get("sources", {}) if isinstance(old, dict) else {}
    lines = []
    for name in sorted(set(old_sources) | set(new["sources"])):
        before, after = old_sources.get(name), new["sources"].get(name)
        if before == after:
            continue
        if before is None:
            lines.append(f"- **{name}**: added ({after['url']})")
        elif after is None:
            lines.append(f"- **{name}**: removed from the watch list")
        else:
            field = "revision" if after["kind"] == "git" else "sha256"
            old_value = before.get(field, "?")
            lines.append(
                f"- **{name}**: {field} `{old_value[:12]}` -> `{after[field][:12]}` ({after['url']})"
            )
    return "\n".join(lines)


def update(watch_path=WATCH, lock_path=LOCK, summary_path=None, resolver=resolve):
    """The online verb. Returns an exit code; writes the lock only when it changed."""
    try:
        new = resolver(load_watch(watch_path))
        try:
            old = load_json(lock_path) if Path(lock_path).exists() else None
        except SpecsError:
            old = None  # an unreadable lock is replaced; the diff then shows everything as added
    except SpecsError as error:
        print(f"specs: {error}", file=sys.stderr)
        return 1
    changes = describe_changes(old, new)
    if not changes:
        print("specs: nothing moved; lock unchanged")
        return 0
    Path(lock_path).write_text(render(new), encoding="utf-8")
    print("specs: lock updated\n" + changes)
    if summary_path:
        Path(summary_path).write_text(changes + "\n", encoding="utf-8")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="./dev specs", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="verb", required=True)
    sub.add_parser("check", help="offline: validate specs.lock against the watch list")
    up = sub.add_parser("update", help="online: re-resolve the sources and rewrite specs.lock")
    up.add_argument("--summary", help="also write the list of changes (Markdown) to this file")
    args = parser.parse_args(argv)
    return check() if args.verb == "check" else update(summary_path=args.summary)


if __name__ == "__main__":
    sys.exit(main())
