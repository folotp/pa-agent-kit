#!/usr/bin/env python3
"""`./dev sync <rev> <target>`: copy the core at <rev> into a consumer repository, as one commit.

Run from the workshop (this repository). <rev> is a tag (`harness-vX.Y`) or any commit-ish; the core
is read from git at that revision, never from the working tree, so two runs of one tag give the same
bytes. <target> is the consumer's checkout.

What it writes in the target, on a new branch `harness-sync/<rev>`, in one commit:
  1. `.harness/`: replaced as a whole by the files named in `harness/core.files`, byte for byte.
     Nothing in it is ever merged or edited in place, so there is nothing to resolve.
     Every file is read from the resolved commit, not the revision name. `.harness/VERSION` records
     the revision and commit; `.harness/CHECKSUMS` lists mode, sha256 and path per file, which
     `./dev check` verifies. The checksum detects drift, not tampering: an agent could change both.
  2. Root files, written only where the target has none: the `dev` shim, the agent bindings of
     `harness/bindings/` and the `CLAUDE.md` stub. The consumer's own files are never overwritten,
     but one that differs leaves part of the core unwired, so sync refuses (exit 1, nothing
     written) unless `--keep-root <file>` names it; a kept file is reported with what stays unwired.
  2b. Starting points (STARTERS), written only where the target has none and never compared after:
     `AGENTS.md` from `templates/AGENTS.md` (a heading and an empty marked block, filled in step 3)
     and `.github/dependabot.yml` from `templates/dependabot.yml`. An existing one is kept and
     reported. A `CLAUDE.md` whose first line is not `@AGENTS.md` is reported: Claude Code would
     not read the shared block.
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


def core_files(commit):
    """Return {path under harness/: (mode, bytes)} for the core at `commit`.

    `commit` is the resolved commit ID, never a revision name: a tag or branch that moves while
    sync runs could otherwise give files that disagree with VERSION (Codex C6).
    """
    manifest = git(WORKSHOP, "show", f"{commit}:harness/core.files").stdout
    wanted = [l.strip() for l in manifest.splitlines() if l.strip() and not l.startswith("#")]
    files = {}
    for entry in wanted:
        listing = git(WORKSHOP, "ls-tree", "-r", commit, "--", f"harness/{entry}").stdout.splitlines()
        if not listing:
            raise SyncError(f"core.files names {entry!r}, which does not exist at {commit[:12]}")
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


def root_files(files):
    """Return {root file of the consumer: the core file it is a copy of}."""
    roots = {"dev": "templates/dev", "CLAUDE.md": "templates/CLAUDE.md"}
    for name in files:
        if name.startswith("bindings/"):
            roots[name[len("bindings/"):]] = name
    return roots


def unwired(dest):
    """What stays unwired while the root file `dest` is not the core's template (finding K22)."""
    clients = {".claude/settings.json": "Claude Code", ".codex/hooks.json": "Codex", ".agents/hooks.json": "Antigravity"}
    if dest == "dev":
        return "the core dispatcher (./dev check, gate, release verbs, git hooks of ./dev setup)"
    if dest in clients:
        return f"the core guard hook for {clients[dest]}"
    if dest == "CLAUDE.md":
        return "the CLAUDE.md stub that imports AGENTS.md"
    return "the core's copy of this file"


def differing_roots(target, files):
    """Root files that exist in the target and differ from their core template."""
    return sorted(
        dest for dest, source in root_files(files).items()
        if (target / dest).exists() and (target / dest).read_bytes() != files[source][1]
    )


# Starting points, unlike root files: written only where the target has none of the given names,
# then the repository's own file, which it is expected to change (other ecosystems, its own rules),
# so an existing one is never compared with the template and never refused (24g D2, F1).
# {destination: (core template, other names that count as present, note when written, note when kept)}
STARTERS = {
    # Written before the shared block step below, which fills its empty marked block.
    "AGENTS.md": (
        "templates/AGENTS.md", (),
        "its shared block is filled below; write the section 'This repository'",
        "the repository's own; only its marked shared block is replaced",
    ),
    ".github/dependabot.yml": (
        "templates/dependabot.yml", (".github/dependabot.yaml",),
        "review its schedule and add the repository's other ecosystems below its entry",
        "the repository's own; `./dev check` judges its github-actions entry (cooldown, local actions)",
    ),
}


def write_when_absent(target, files):
    """Write each starter of STARTERS the target lacks; return one report line per starter."""
    report = []
    for dest, (source, aliases, written, kept) in STARTERS.items():
        present = [name for name in (dest, *aliases) if (target / name).exists()]
        if present:
            report.append(f"- `{present[0]}` kept as it is ({kept})")
        else:
            mode, data = files[source]
            write(target / dest, data, mode)
            report.append(f"- `{dest}` written from `.harness/{source}` (was absent): {written}")
    return report


def install(target, rev, commit, files, kept=()):
    """Write the target tree. Returns the report lines. `kept` are differing root files that
    the caller named with --keep-root; main() refused any other differing root file before."""
    report = []
    harness = target / ".harness"
    if harness.exists():
        shutil.rmtree(harness)
    for name, (mode, data) in files.items():
        write(harness / name, data, mode)
    write(harness / "VERSION", f"core {rev}\ncommit {commit}\n".encode(), 0o644)
    # One line per file: mode, sha256, path (`./dev check` verifies all three; Codex C6).
    modes = {name: mode for name, (mode, _) in files.items()}
    sums = sorted(
        (p, modes.get(p, 0o644), hashlib.sha256((harness / p).read_bytes()).hexdigest())
        for p in [*files, "VERSION"]
    )
    write(harness / "CHECKSUMS", "".join(f"{m:o} {h} {p}\n" for p, m, h in sums).encode(), 0o644)
    report.append(f"- `.harness/` replaced: {len(files)} core files, VERSION, CHECKSUMS (with modes)")

    for dest, source in sorted(root_files(files).items()):
        mode, data = files[source]
        path = target / dest
        if not path.exists():
            write(path, data, mode)
            report.append(f"- `{dest}` installed (was absent)")
        elif path.read_bytes() != data:
            if dest not in kept:
                raise SyncError(f"{dest} differs from the core template and was not named with --keep-root")
            report.append(
                f"- `{dest}` DIFFERS from the core template; kept by --keep-root, so {unwired(dest)} "
                f"stays unwired (compare with `.harness/{source}`)")

    report.extend(write_when_absent(target, files))

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
    claude = target / "CLAUDE.md"
    if claude.exists() and claude.read_text(encoding="utf-8").split("\n", 1)[0].strip() != "@AGENTS.md":
        report.append("- `CLAUDE.md` does not start with `@AGENTS.md`: Claude Code does not read `AGENTS.md` (and its "
                      "shared block) while `CLAUDE.md` exists; make `@AGENTS.md` its first line (as `.harness/templates/CLAUDE.md`)")

    link = target / ".claude" / "skills"
    if not (link.is_symlink() and os.readlink(link) == "../.agents/skills"):
        report.append(f"- `.claude/skills` is not the symlink to `../.agents/skills`; not changed. To create it: `{SKILLS_COMMAND}`")
    return report


def main(argv):
    parser = argparse.ArgumentParser(prog="./dev sync", description=__doc__.split("\n")[0])
    parser.add_argument("rev", help="core tag (harness-vX.Y) or commit-ish of this repository")
    parser.add_argument("target", help="checkout of the consumer repository")
    parser.add_argument("--pr", action="store_true", help="push the branch and open the PR with gh")
    parser.add_argument("--keep-root", action="append", default=[], metavar="FILE",
                        help="keep this differing root file (dev, CLAUDE.md, a binding) as it is; repeatable")
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

    files = core_files(commit)
    roots = root_files(files)
    unknown = sorted(set(args.keep_root) - set(roots))
    if unknown:
        raise SyncError(f"--keep-root names no root file of the core: {', '.join(unknown)} (root files: {', '.join(sorted(roots))})")
    # A differing root file leaves part of the core unwired (finding K22): refused unless named.
    refused = [dest for dest in differing_roots(target, files) if dest not in args.keep_root]
    if refused:
        lines = "\n".join(f"  {dest}: {unwired(dest)} would stay unwired" for dest in refused)
        raise SyncError(
            f"root files differ from the core templates at {args.rev}:\n{lines}\n"
            "Make each one the template (delete it and sync again, or merge the template into it), "
            "or keep it on purpose with --keep-root <file>.")
    git(target, "switch", "-c", branch)
    try:
        report = install(target, args.rev, commit, files, kept=args.keep_root)
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
