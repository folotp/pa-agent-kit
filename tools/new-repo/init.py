#!/usr/bin/env python3
"""Prepare a new clone using the workshop's released harness and repository baseline."""

import argparse
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sync import sync

import settings

HERE = Path(__file__).resolve().parent
WORKSHOP = sync.WORKSHOP
TAG = re.compile(r"harness-v(\d+)\.(\d+)")
ORIGIN = re.compile(
    r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"(?P<owner>[A-Za-z0-9][A-Za-z0-9-]*)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?"
)
CORE_HOOKS = ".harness/githooks"


class InitError(Exception):
    pass


def repository(target):
    """Identify the clone without contacting GitHub or echoing a remote URL."""
    root = sync.git(target, "rev-parse", "--show-toplevel", check=False)
    if root.returncode or Path(root.stdout.strip()).resolve() != target:
        raise InitError("Use the root of a new Git checkout.")
    common_dir = sync.git(target, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    workshop_git = sync.git(WORKSHOP, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    if Path(common_dir).resolve() == Path(workshop_git).resolve():
        raise InitError("Use a new consumer clone outside the workshop.")
    url = sync.git(target, "remote", "get-url", "origin", check=False)
    match = ORIGIN.fullmatch(url.stdout.strip())
    if not match or match["repo"] in {".", ".."}:
        raise InitError("Set origin to a GitHub repository using HTTPS or SSH without embedded credentials.")
    return match["owner"], match["repo"]


def select_release(requested):
    tags = sync.git(WORKSHOP, "tag", "--list", "harness-v*").stdout.splitlines()
    released = {tag: tuple(map(int, TAG.fullmatch(tag).groups())) for tag in tags if TAG.fullmatch(tag)}
    if not released or (requested and requested not in released):
        raise InitError("Use a local harness-vX.Y release tag. Refresh the workshop checkout if it is missing.")
    tag = requested or max(released, key=released.get)
    commit = sync.git(WORKSHOP, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}").stdout.strip()
    return tag, commit


def write_mise(stage, profile, ci_template):
    """Use only the locked tools that this checkout's core, gate or CI actually runs."""
    lock = (WORKSHOP / "mise.lock").read_text(encoding="utf-8")
    header, *blocks = re.split(r"(?m)(?=^\[\[tools\.)", lock)
    tools = {block.splitlines()[0].removeprefix("[[tools.").removesuffix("]]"): block for block in blocks}
    names = ["actionlint", "jq", "ruby", "shellcheck"]
    if profile == "live":
        names.append("gh")
        gh_lock = (HERE / "live-gh.mise.lock").read_text(encoding="utf-8")
        _, heading, body = gh_lock.partition("[[tools.gh]]")
        tools["gh"] = heading + body
    names.sort()
    start_version = re.search(r"(?m)^ *MISE_VERSION: v([\d.]+)$", ci_template)
    if not start_version:
        raise InitError("The selected CI template has no pinned mise version.")

    pins = []
    for name in names:
        match = re.search(r'^version = ("[^"]+")$', tools.get(name, ""), re.M)
        if not match:
            raise InitError(f"No exact mise lock entry for {name}.")
        pins.append(f"{name} = {match[1]}")

    settings = (
        f'min_version = "{start_version[1]}"\n\n'
        "[settings]\nlocked = true\nauto_install = false\n"
        "exec_auto_install = false\nnot_found_auto_install = false\nlockfile = true\n"
    )
    (stage / "mise.toml").write_text(settings + "\n[tools]\n" + "\n".join(pins) + "\n", encoding="utf-8")
    selected_lock = "\n\n".join([header.rstrip(), *(tools[name].rstrip() for name in names)]) + "\n"
    (stage / "mise.lock").write_text(selected_lock, encoding="utf-8")
    harness = (
        f'profile = "{profile}"\n'
        f'tools = {json.dumps(names)}\n\n'
        '[checks]\nworkflows = "actionlint -shellcheck=shellcheck -pyflakes="\n'
    )
    if profile == "live":
        harness += (
            '\n# Fill the values and uncomment the table together when provisioning the gate.\n'
            '# [gate]\n# repo = ""\n# merger = ""\n# verb = ""\n'
            '# release = ""\n# ci = ""\n# required = []\n# guarded = []\n'
            '# loaded = []\n# keep_env = []\n'
        )
    (stage / "harness.toml").write_text(harness, encoding="utf-8")


def stage_tree(stage, tag, commit, profile, owner, baseline):
    """Run the shared sync installer in isolation so a collision can never rewrite the clone."""
    files = sync.core_files(commit)
    sync.install(stage, tag, commit, files)
    (stage / ".claude/skills").symlink_to("../.agents/skills")
    dependabot = stage / ".github/dependabot.yml"
    if not dependabot.is_file():
        raise InitError("The release lacks the Dependabot starter required by the baseline.")
    comment = "# The mise-bump workflow updates mise.toml and mise.lock."
    if "mise-bump" not in dependabot.read_text(encoding="utf-8"):
        with dependabot.open("a", encoding="utf-8") as output:
            output.write(f"\n{comment}\n")
    codeowners = baseline["files"][".github/CODEOWNERS"]["value"]
    (stage / ".github/CODEOWNERS").write_text(codeowners.format(repository_owner=owner), encoding="utf-8")
    workflows = stage / ".github/workflows"
    workflows.mkdir(exist_ok=True)
    ci = files["templates/ci.yml"][1]
    (workflows / "ci.yml").write_bytes(ci)
    bump = files.get("templates/mise-bump.yml")
    bump_bytes = bump[1] if bump else (WORKSHOP / "harness/templates/mise-bump.yml").read_bytes()
    (workflows / "mise-bump.yml").write_bytes(bump_bytes)
    write_mise(stage, profile, ci.decode("utf-8"))


def contained_path(root, relative):
    """Reject redirected ancestors before inspecting or creating a managed file."""
    for parent in relative.parents:
        path = root / parent
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise InitError(f"Resolve the existing path at {parent}.")
    return root / relative


def identical(source, destination):
    if source.is_symlink():
        return destination.is_symlink() and os.readlink(source) == os.readlink(destination)
    return (
        not destination.is_symlink()
        and destination.is_file()
        and stat.S_IMODE(source.stat().st_mode) == stat.S_IMODE(destination.stat().st_mode)
        and source.read_bytes() == destination.read_bytes()
    )


def install_missing(stage, target):
    """Preflight all collisions. Publish each new regular file without replacing another file."""
    planned = sorted(path.relative_to(stage) for path in stage.rglob("*") if path.is_symlink() or path.is_file())
    missing = []
    for relative in planned:
        destination = contained_path(target, relative)
        if not destination.exists() and not destination.is_symlink():
            missing.append(relative)
        elif not identical(stage / relative, destination):
            raise InitError(f"Existing {relative} differs from the starter. No files were written.")
    alternate = contained_path(target, Path(".github/dependabot.yaml"))
    if alternate.exists() or alternate.is_symlink():
        raise InitError("Existing .github/dependabot.yaml would conflict with the starter.")
    core = target / ".harness"
    expected = {path for path in planned if path.parts[0] == ".harness"}
    if core.exists() and any(
        path.relative_to(target) not in expected
        for path in core.rglob("*") if path.is_symlink() or path.is_file()
    ):
        raise InitError("The existing core contains unexpected files. Use a new clone.")
    for relative in missing:
        source = stage / relative
        destination = contained_path(target, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            if source.is_symlink():
                destination.symlink_to(os.readlink(source))
            else:
                with tempfile.NamedTemporaryFile(dir=destination.parent) as temporary:
                    temporary.write(source.read_bytes())
                    temporary.flush()
                    os.chmod(temporary.name, stat.S_IMODE(source.stat().st_mode))
                    os.link(temporary.name, destination)
        except FileExistsError:
            if not identical(source, destination):
                raise InitError(f"{relative} changed during setup. Review it before retrying.") from None
    return len(missing)


def run(argv=None):
    baseline = json.loads((HERE / "baseline.json").read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path, help="root of the new clone")
    parser.add_argument("--profile", choices=baseline["profiles"], required=True)
    parser.add_argument("--tag", help="local release tag (default: newest harness-vX.Y)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan with no writes or API calls")
    parser.add_argument(
        "--defer-hooks", action="store_true",
        help="prepare files before the owner creates main, then rerun without this option",
    )
    parser.add_argument("--apply-settings", action="store_true", help="apply GitHub settings before the initial push")
    parser.add_argument("--yes", action="store_true", help="confirm the owner approved the settings write")
    args = parser.parse_args(argv)
    if args.apply_settings and not args.dry_run and not (args.defer_hooks and args.yes):
        parser.error("--apply-settings requires --defer-hooks and explicit owner approval (--yes)")
    if args.apply_settings and not args.dry_run and not os.environ.get("GH_TOKEN"):
        raise InitError("Run --apply-settings through the owner token command in your own terminal.")
    target = args.checkout.resolve()
    owner, name = repository(target)
    tag, commit = select_release(args.tag)
    active_hooks = sync.git(target, "config", "--get", "core.hooksPath", check=False).stdout.strip()
    if active_hooks and (args.defer_hooks or active_hooks != CORE_HOOKS):
        raise InitError("This clone already has a hooks path. Use its current hooks and leave them active.")

    if args.dry_run:
        print(f"Plan for {owner}/{name} ({args.profile}):")
        print(f"  Install released core {tag} ({commit[:12]}), agent files and locked tool configuration.")
        for path in baseline["files"]:
            print(f"  Install {path} if absent.")
        print("  Defer hook activation until after the owner's initial push." if args.defer_hooks
              else "  Run ./dev setup to install locked tools and activate hooks.")
        settings.dry_plan(f"{owner}/{name}", args.profile, baseline, apply=True, handoff=False)
        print("done: plan printed")
        print("left for PA: perform the initial workflow push with the owner token")
        print("next: rerun without --dry-run when ready")
        return 0

    with tempfile.TemporaryDirectory(prefix="workshop-new-repo-") as stage:
        stage = Path(stage)
        stage_tree(stage, tag, commit, args.profile, owner, baseline)
        count = install_missing(stage, target)
    if not args.defer_hooks:
        command = "check" if active_hooks == CORE_HOOKS else "setup"
        subprocess.run(["./dev", command], cwd=target, check=True)
    if args.apply_settings:
        result = settings.run(["apply", f"{owner}/{name}", "--profile", args.profile, "--planned-mise-bump", "--yes"])
        if result:
            return result
    print(f"done: {tag} prepared; {count} new files or links")
    if args.defer_hooks:
        print("left for PA: approve the owner-token push of the initial workflow commit")
        print("next: /dev-repo-create")
    else:
        print("left for PA: review the GitHub settings and workflow handoff")
        print(f'next: cd {shlex.quote(str(target))} && ./dev ci')
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except (InitError, settings.SettingsError, sync.SyncError, OSError, subprocess.CalledProcessError) as error:
        print(f"init: {error}", file=sys.stderr)
        sys.exit(1)
