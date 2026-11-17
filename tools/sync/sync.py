#!/usr/bin/env python3
"""`./dev sync <rev> <target>`: copy the core at <rev> into a consumer repository, as one commit.

Run from the workshop (this repository). <rev> is a tag (`harness-vX.Y`) or any commit-ish; the core
is read from git at that revision, never from the working tree, so two runs of one tag give the same
bytes. <target> is the consumer's checkout.

What it writes in the target, on a new branch `harness-sync/<rev>`, in one commit:
  1. `.harness/`: replaced as a whole by the files named in `harness/core.files`, byte for byte.
     Nothing in it is ever merged or edited in place, so there is nothing to resolve.
     `.harness/VERSION` records the revision; `.harness/CHECKSUMS` lists a sha256 per file, which
     `./dev check` verifies. The checksum detects drift, not tampering: an agent could change both.
  2. Root files, written only where the target has none: the `dev` shim, the agent bindings of
     `harness/bindings/` and the `CLAUDE.md` stub. A file that exists and differs is left alone and
     named in the report: the consumer's own settings are never overwritten.
  3. The shared block of `AGENTS.md` (between `harness:shared:begin` and `harness:shared:end`):
     replaced when both markers are present, otherwise reported.
  4. The `.claude/skills` symlink is only checked and reported.
`harness.toml` and `mise.toml` belong to the consumer and are never touched.

With `--pr` the branch is pushed and one PR is opened with `gh`, its body holding the report. The
caller supplies the credentials (an agent runs the whole command under harness/gh-token.sh); this
script never reads or prints a token. Without `--pr` nothing leaves the machine.

Refuses: a target that is not the top of a git work tree, is this repository, or has uncommitted
changes; an existing branch of the same name; a core file whose name contains whitespace.
Stdlib and git only.
"""

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

WORKSHOP = Path(__file__).resolve().parent.parent.parent
BEGIN, END = "<!-- harness:shared:begin -->", "<!-- harness:shared:end -->"
SKILLS_COMMAND = "mkdir -p .agents/skills .claude && ln -s ../.agents/skills .claude/skills"


class SyncError(Exception):
    pass


def git(cwd, *args, check=True, text=True):
    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=text)
    if check and result.returncode != 0:
        detail = result.stderr if text else result.stderr.decode(errors="replace")
        raise SyncError(f"git {' '.join(args[:2])} failed: {detail.strip()}")
    return result


def core_files(rev):
    """Return {path under harness/: (mode, bytes)} for the core at `rev`."""
    manifest = git(WORKSHOP, "show", f"{rev}:harness/core.files").stdout
    wanted = [l.strip() for l in manifest.splitlines() if l.strip() and not l.startswith("#")]
    files = {}
    for entry in wanted:
        listing = git(WORKSHOP, "ls-tree", "-r", rev, "--", f"harness/{entry}").stdout.splitlines()
        if not listing:
            raise SyncError(f"core.files names {entry!r}, which does not exist at {rev}")
        for line in listing:
            meta, path = line.split("\t", 1)
            mode, kind, blob = meta.split()
            if kind != "blob" or mode == "120000":
                raise SyncError(f"{path}: only regular files can be core")
            name = path[len("harness/"):]
            if re.search(r"\s", name):
                raise SyncError(f"{path}: whitespace in a core file name")
            data = git(WORKSHOP, "cat-file", "blob", blob, text=False).stdout
            files[name] = (0o755 if mode == "100755" else 0o644, data)
    return files


def write(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)


def replace_shared_block(current, template):
    """Return the new AGENTS.md text, or None when the markers are not both there exactly once."""
    if current.count(BEGIN) != 1 or current.count(END) != 1 or current.index(BEGIN) > current.index(END):
        return None
    head, rest = current.split(BEGIN, 1)
    tail = rest.split(END, 1)[1]
    return head + template.strip("\n") + tail


def install(target, rev, commit, files):
    """Write the target tree. Returns the report lines."""
    report = []
    harness = target / ".harness"
    if harness.exists():
        shutil.rmtree(harness)
    for name, (mode, data) in files.items():
        write(harness / name, data, mode)
    write(harness / "VERSION", f"core {rev}\ncommit {commit}\n".encode(), 0o644)
    sums = sorted(
        (hashlib.sha256((harness / p).read_bytes()).hexdigest(), p)
        for p in [*files, "VERSION"]
    )
    write(harness / "CHECKSUMS", "".join(f"{h}  {p}\n" for h, p in sums).encode(), 0o644)
    report.append(f"- `.harness/` replaced: {len(files)} core files, VERSION, CHECKSUMS")

    # Root file -> the core file it comes from.
    roots = {"dev": "templates/dev", "CLAUDE.md": "templates/CLAUDE.md"}
    for name in files:
        if name.startswith("bindings/"):
            roots[name[len("bindings/"):]] = name
    for dest, source in sorted(roots.items()):
        mode, data = files[source]
        path = target / dest
        if not path.exists():
            write(path, data, mode)
            report.append(f"- `{dest}` installed (was absent)")
        elif path.read_bytes() != data:
            report.append(f"- `{dest}` DIFFERS from the core template; left as it is (compare with `.harness/{source}`)")

    agents = target / "AGENTS.md"
    template = files["templates/AGENTS.shared.md"][1].decode()
    if not agents.exists():
        report.append("- `AGENTS.md` is absent: the shared block was not installed")
    else:
        old = agents.read_text(encoding="utf-8")
        new = replace_shared_block(old, template)
        if new is None:
            report.append("- `AGENTS.md` has no single marked shared block: not touched")
        elif new != old:
            agents.write_text(new, encoding="utf-8")
            report.append("- `AGENTS.md`: shared block replaced")
        else:
            report.append("- `AGENTS.md`: shared block already current")

    link = target / ".claude" / "skills"
    if not (link.is_symlink() and os.readlink(link) == "../.agents/skills"):
        report.append(f"- `.claude/skills` is not the symlink to `../.agents/skills`; not changed. To create it: `{SKILLS_COMMAND}`")
    return report


def main(argv):
    parser = argparse.ArgumentParser(prog="./dev sync", description=__doc__.split("\n")[0])
    parser.add_argument("rev", help="core tag (harness-vX.Y) or commit-ish of this repository")
    parser.add_argument("target", help="checkout of the consumer repository")
    parser.add_argument("--pr", action="store_true", help="push the branch and open the PR with gh")
    args = parser.parse_args(argv)

    target = Path(args.target).resolve()
    top = git(target, "rev-parse", "--show-toplevel", check=False)
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != target:
        raise SyncError(f"{target} is not the top of a git work tree")
    if target == WORKSHOP:
        raise SyncError("the target is the workshop itself")
    if git(target, "status", "--porcelain").stdout.strip():
        raise SyncError("the target has uncommitted changes; sync starts from a clean tree")
    commit = git(WORKSHOP, "rev-parse", "--verify", f"{args.rev}^{{commit}}").stdout.strip()
    branch = "harness-sync/" + re.sub(r"[^A-Za-z0-9._-]", "-", args.rev)
    if git(target, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0:
        raise SyncError(f"branch {branch} already exists in the target")

    files = core_files(args.rev)
    git(target, "switch", "-c", branch)
    try:
        report = install(target, args.rev, commit, files)
        git(target, "add", "-A")
        if not git(target, "status", "--porcelain").stdout.strip():
            raise SyncError("nothing changed: the target already has this core")
        body = f"Sync the harness core at `{args.rev}` ({commit[:12]}).\n\n" + "\n".join(report) + "\n"
        git(target, "commit", "-q", "-m", f"chore: sync harness core {args.rev}", "-m", body)
    except SyncError:
        git(target, "switch", "-", check=False)
        git(target, "branch", "-D", branch, check=False)
        raise
    print(body)
    print(git(target, "show", "--stat", "--format=", "HEAD").stdout)
    if args.pr:
        git(target, "push", "origin", f"HEAD:refs/heads/{branch}")
        title = f"chore: sync harness core {args.rev}"
        pr = subprocess.run(
            ["gh", "pr", "create", "--head", branch, "--title", title, "--body", body],
            cwd=target, capture_output=True, text=True,
        )
        if pr.returncode != 0:
            raise SyncError(f"gh pr create failed: {pr.stderr.strip()}")
        print(pr.stdout.strip())
    else:
        print(f"Branch {branch} committed in {target}. Review `git show`, then push it and open the PR (or rerun with --pr).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SyncError as error:
        print(f"sync: {error}", file=sys.stderr)
        sys.exit(1)
