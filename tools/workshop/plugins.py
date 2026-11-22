#!/usr/bin/env python3
"""Prepare a workshop plugin or advance its release. Owner operations are printed for PA."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
CLAUDE_MARKETPLACE = ".claude-plugin/marketplace.json"
BOTS = ("claude", "codex", "antigravity")
BUMPS = ("patch", "minor", "major")
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tag_release = load_script("tag-release.py")
release_plugins = tag_release.release_plugins
plugin_zip = release_plugins.plugin_zip


def run(*args, repo=ROOT):
    result = subprocess.run(args, cwd=repo, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{shlex.join(map(str, args))} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def as_bot(bot, *args, repo=ROOT):
    return run(repo / "harness/gh-token.sh", bot, "--", *args, repo=repo)


def ending(done, left, next_command):
    print(f"done: {done}\nleft for PA: {left}\nnext: {next_command}")


def short_text(value):
    if not value or any(ord(char) < 32 or char == "|" for char in value):
        raise argparse.ArgumentTypeError("provide one line of text without a table separator")
    return value


def plugin_name(value):
    if not NAME.fullmatch(value) or len(value) > 64:
        raise argparse.ArgumentTypeError("use at most 64 lowercase letters, digits and single hyphens")
    return value


def simple_version(value):
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value):
        raise argparse.ArgumentTypeError("use a version such as 0.1.0")
    return value


def feature_worktree(repo):
    branch = run("git", "branch", "--show-current", repo=repo)
    worktree_git_dir = run("git", "rev-parse", "--git-dir", repo=repo)
    common_dir = run("git", "rev-parse", "--git-common-dir", repo=repo)
    if not branch or branch in ("main", "master") or worktree_git_dir == common_dir:
        raise ValueError("use a named feature branch in a separate git worktree")


def validate(repo):
    run(sys.executable, "-B", "scripts/validate-marketplace.py", repo=repo)


def create_plugin(args, repo=ROOT):
    path = repo / "plugins" / args.plugin
    if path.exists() or path.is_symlink():
        raise ValueError(f"plugins/{args.plugin} already exists. Use /dev-plugin-release {args.plugin} for a version bump")
    plugin = args.plugin
    description = args.description
    tags = [tag.strip() for tag in (args.tags or "").split(",") if tag.strip()]
    manifest = {"name": plugin, "version": args.version, "description": description}
    entry = {"name": plugin, "source": f"./plugins/{plugin}", "description": description,
             "category": args.category, "tags": tags}

    marketplace = repo / CLAUDE_MARKETPLACE
    readme = repo / "README.md"
    marketplace_text = marketplace.read_text()
    readme_text = readme.read_text()
    entries = json.loads(marketplace_text)["plugins"]
    if any(item["name"] == plugin or item["source"] == entry["source"] for item in entries):
        raise ValueError(f"{plugin} already has a marketplace entry")
    if re.search(rf"(?m)^\|\s*\[\x60{re.escape(plugin)}\x60\]", readme_text):
        raise ValueError(f"{plugin} already has a README row")

    # Preserve every existing entry, including the compact tags arrays.
    array_start = re.search(r'(?m)^  "plugins": \[$', marketplace_text)
    array_end = re.search(r"(?m)^  \](?=,?$)", marketplace_text)
    if not array_start or not array_end or array_end.start() <= array_start.end():
        raise ValueError("expected a multiline plugins array in the marketplace manifest")
    entry_lines = ["    {"]
    entry_lines.extend(
        f"      {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)},"
        for key, value in entry.items()
    )
    entry_lines[-1] = entry_lines[-1].removesuffix(",")
    entry_lines.append("    }")
    prefix = marketplace_text[:array_end.start()].rstrip()
    updated_marketplace = prefix + ("," if entries else "") + "\n" + "\n".join(entry_lines) + "\n"
    updated_marketplace += marketplace_text[array_end.start():]
    json.loads(updated_marketplace)

    rows = list(re.finditer(r"(?m)^\|\s*\[\x60[^|\n]+\x60\]\(plugins/[^)\n]+\)\s*\|.*$", readme_text))
    if not rows:
        raise ValueError("could not find the plugins table in README.md")
    row = f"| [\x60{plugin}\x60](plugins/{plugin}/) | {args.version} | in-repo | {description} |"
    index = rows[-1].end()
    updated_readme = readme_text[:index] + "\n" + row + readme_text[index:]

    frontmatter = f"name: {plugin}\ndescription: {json.dumps(description, ensure_ascii=False)}\n"
    stub = {
        "skills": (f"skills/{plugin}/SKILL.md", f"---\n{frontmatter}---\n\nAdd the skill instructions here.\n"),
        "commands": (f"commands/{plugin}.md", f"---\n{frontmatter}---\n\nAdd the command instructions here.\n"),
        "agents": (f"agents/{plugin}.md", f"---\n{frontmatter}---\n\nAdd the agent instructions here.\n"),
        "hooks": ("hooks/hooks.json", '{\n  "hooks": {}\n}\n'),
    }
    stub_path, stub_text = stub[args.component]
    if args.dry_run:
        ending(f"planned {plugin} {args.version} with {stub_path}", "review the scaffold plan", f"/dev-plugin-create {plugin}")
        return

    feature_worktree(repo)
    validate(repo)
    generated = {
        path / ".claude-plugin/plugin.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        path / stub_path: stub_text,
    }
    if marketplace.read_text() != marketplace_text or readme.read_text() != readme_text:
        raise ValueError("marketplace or README changed while planning; run the command again")
    path.mkdir()
    try:
        for target, content in generated.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x") as file:
                file.write(content)
        marketplace.write_text(updated_marketplace)
        readme.write_text(updated_readme)
        validate(repo)
    except (OSError, RuntimeError):
        # mkdir above succeeds only if this invocation owns the new plugin directory.
        shutil.rmtree(path)
        marketplace.write_text(marketplace_text)
        readme.write_text(readme_text)
        raise

    ending(f"scaffolded and validated plugins/{plugin}", "fill in the component stub", f"edit plugins/{plugin}/{stub_path}")


def next_version(value, increment):
    base, _, prerelease = value.partition("-")
    parts = [int(item) for item in base.split(".")]
    index = {"major": 0, "minor": 1, "patch": 2}[increment]
    if not (prerelease and increment == "patch"):
        parts[index] += 1
        parts[index + 1:] = [0] * (2 - index)
    return ".".join(map(str, parts))


def open_bump_pr(bot, repo, source, plugin):
    pulls = json.loads(as_bot(bot, "gh", "pr", "list", "--base", "main", "--state", "open",
                              "--limit", "1000", "--json", "url,headRefName,files", repo=repo))
    manifests = {f"{source}/{name}" for name in release_plugins.MANIFEST_NAMES}
    return next((item["url"] for item in pulls
                 if item["headRefName"].startswith(f"bump/{plugin}-")
                 or any(entry["path"] in manifests for entry in item["files"])), None)


def update_version(repo, source, plugin, before, after):
    """Edit manifest and README precisely, after validating both replacements."""
    manifest = next((repo / source / name for name in release_plugins.MANIFEST_NAMES
                     if (repo / source / name).is_file()), None)
    if manifest is None or not manifest.resolve().is_relative_to(repo / source):
        raise ValueError(f"{plugin} has no usable manifest")
    manifest = manifest.resolve()
    text = manifest.read_text()
    pattern = r'("version"\s*:\s*")' + re.escape(before) + r'(")'
    updated, count = re.subn(pattern, lambda match: match[1] + after + match[2], text)
    if count != 1 or json.loads(updated)["version"] != after:
        raise ValueError(f"expected one canonical version of {before} in {manifest.relative_to(repo)}")
    readme = repo / "README.md"
    readme_text = readme.read_text()
    row = rf"(^\|\s*\[\x60{re.escape(plugin)}\x60\]\([^|\n]+\)\s*\|\s*){re.escape(before)}(?=\s*\|)"
    updated_readme, count = re.subn(row, lambda match: match[1] + after, readme_text, flags=re.M)
    if count != 1:
        raise ValueError(f"expected one README version cell of {before} for {plugin}")
    manifest.write_text(updated)
    try:
        readme.write_text(updated_readme)
    except OSError:
        manifest.write_text(text)
        raise


def submit_bump(args, repo, sha, source, before, after):
    """Keep a retryable worktree for the exact version, and push only its branch."""
    branch = f"bump/{args.plugin}-{after}"
    root_checkout = Path(run("git", "worktree", "list", "--porcelain", repo=repo)
                         .splitlines()[0].removeprefix("worktree "))
    worktree = root_checkout.parent / "Worktrees" / root_checkout.name / branch.replace("/", "-")
    if not worktree.exists():
        worktree.parent.mkdir(parents=True, exist_ok=True)
        run("git", "worktree", "add", "-b", branch, str(worktree), sha, repo=repo)
    feature_worktree(worktree)
    if run("git", "branch", "--show-current", repo=worktree) != branch:
        raise ValueError(f"{worktree} is on a different branch")
    validate(worktree)
    current = release_plugins.version_at(worktree, "HEAD", source)
    if run("git", "status", "--porcelain", repo=worktree):
        raise ValueError(f"review the pending changes in {worktree} before resuming")
    if current == before and run("git", "rev-parse", "HEAD", repo=worktree) == sha:
        update_version(worktree, source, args.plugin, before, after)
        validate(worktree)
        run("./dev", "check", repo=worktree)
        run("git", "add", "--", source, "README.md", repo=worktree)
        as_bot(args.bot, "git", "commit", "-m", f"chore({args.plugin}): bump to {after}", repo=worktree)
    elif current != after or run("git", "rev-parse", "HEAD^", repo=worktree) != sha:
        raise ValueError(f"{worktree} does not contain the expected bump from {before} to {after}")

    run("./dev", "ci", repo=worktree)
    as_bot(args.bot, "git", "push", "origin", f"HEAD:refs/heads/{branch}", repo=worktree)
    url = as_bot(args.bot, "gh", "pr", "create", "--draft", "--base", "main", "--head", branch,
                 "--title", f"chore({args.plugin}): bump to {after}",
                 "--body", f"Bump the plugin manifest and README version to {after}.", repo=worktree)
    ending(f"opened draft bump PR {url}", "review, mark ready and merge it when checks pass", "/dev-status")


def owner_next(command, args, done):
    print(shlex.join(command))
    ending(done, "give explicit go, then run the printed command and choose Allow once in the "
           "Keychain dialog for github-owner-token", f"/dev-plugin-release {args.plugin}")


def release_plugin(args, repo=ROOT):
    clean_env = {key: value for key, value in os.environ.items()
                 if key not in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")}
    if subprocess.run(["gh", "auth", "status"], cwd=repo, env=clean_env,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise ValueError("gh reports a stored login. Stop and tell PA")
    run("git", "fetch", "--quiet", "--tags", "origin", repo=repo)
    rev = run("git", "rev-parse", "origin/main", repo=repo)
    source = plugin_zip.marketplace_path(repo, rev, args.plugin)
    version = release_plugins.version_at(repo, rev, source)
    if not version or not release_plugins.SEMVER.fullmatch(version):
        raise ValueError(f"{args.plugin} has no valid version on origin/main")
    tag = f"{args.plugin}/v{version}"
    tags = tag_release.remote_tag_names(repo, "origin")
    command = f"/dev-plugin-release {args.plugin}"

    if tag not in tags:
        if pending_pr(args, repo, source):
            return
        try:
            planned, sha = tag_release.plan_tag(repo, args.plugin, rev, tags)
        except tag_release.BumpRequired:
            if not args.increment:
                ending(f"{tag} has no taggable bump at the latest plugin change",
                       "choose patch, minor or major", command)
                return
            plan_bump(args, repo, rev, source, version)
        else:
            owner_next(["harness/gh-token.sh", "owner", "--", "python3", "-B", "scripts/tag-release.py",
                        args.plugin, "--expect-commit", sha], args, f"tag dry run passed for {planned} at {sha}")
        return

    release = release_plugins.find_release(as_bot(args.bot, *release_plugins.RELEASE_LIST, repo=repo), tag)
    if release is None:
        ending(f"{tag} is pushed", "wait for the Release workflow to draft and attach its assets", command)
        return
    if release["draft"]:
        sha = run("git", "rev-parse", f"refs/tags/{tag}^{{commit}}", repo=repo)
        run("git", "merge-base", "--is-ancestor", sha, rev, repo=repo)
        release_plugins.release_for_tag(repo, tag, sha)
        _, _, files, _ = plugin_zip.collect(repo, sha, args.plugin)
        expected = {f"{args.plugin}-v{version}.plugin"}
        expected.update(path.split("/")[1] + ".zip" for path in files
                        if re.fullmatch(r"skills/[^/]+/SKILL\.md", path))
        assets = {asset["name"] for asset in release["assets"]
                  if asset["state"] == "uploaded" and asset["size"] > 0}
        if expected != assets:
            differences = sorted(expected ^ assets)
            ending(f"draft {tag} still has asset differences: {', '.join(differences)}",
                   "check the Release workflow and wait for the expected assets", command)
            return
        release_id = int(release["id"])
        owner_next(["harness/gh-token.sh", "owner", "--", "gh", "api", "-X", "PATCH",
                    f"repos/{{owner}}/{{repo}}/releases/{release_id}", "-f", f"tag_name={tag}", "-F", "draft=false",
                    "--jq", "{id,tag_name,draft,immutable}"], args,
                   f"verified draft {release_id} and {len(expected)} uploaded assets for {tag}")
        return
    if not release.get("immutable"):
        raise ValueError(f"published release {tag} did not report immutability")
    if not args.increment:
        print("Claude Code: /plugin marketplace update pa-marketplace, then /reload-plugins")
        print("Codex: codex plugin marketplace upgrade")
        ending(f"{tag} is published and immutable", "refresh the marketplace in your client",
               "/plugin marketplace update pa-marketplace")
        return

    if not pending_pr(args, repo, source):
        plan_bump(args, repo, rev, source, version)


def pending_pr(args, repo, source):
    url = open_bump_pr(args.bot, repo, source, args.plugin)
    if url:
        ending(f"found open plugin PR {url}", "review and merge it when ready", "/dev-status")
    return bool(url)


def plan_bump(args, repo, rev, source, version):
    after = next_version(version, args.increment)
    command = f"/dev-plugin-release {args.plugin} {args.increment}"
    if args.open_pr is None:
        ending(f"planned {args.plugin} {version} to {after}", "authorize the bot to commit and open a draft bump PR",
               command)
        return
    if args.open_pr != after:
        raise ValueError(f"the approved bump was to {args.open_pr}, but the current plan is to {after}")
    submit_bump(args, repo, rev, source, version, after)



class CommandParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"plugins: {message}", file=sys.stderr)
        ending("the command needs different arguments", "supply the requested choices", "/dev-help")
        self.exit(2)


def main():
    parser = CommandParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    release = modes.add_parser("release")
    release.add_argument("plugin", type=plugin_name)
    release.add_argument("increment", choices=BUMPS, nargs="?")
    release.add_argument("--bot", required=True, choices=BOTS)
    release.add_argument("--open-pr", metavar="APPROVED_VERSION", type=simple_version,
                         help="open the planned bump PR after explicit approval")
    create = modes.add_parser("create")
    create.add_argument("plugin", type=plugin_name)
    create.add_argument("--description", required=True, type=short_text)
    create.add_argument("--category", required=True, type=short_text)
    create.add_argument("--tags", type=short_text)
    create.add_argument("--version", default="0.1.0", type=simple_version)
    create.add_argument("--component", choices=("skills", "commands", "agents", "hooks"), default="skills")
    create.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.mode == "release" and args.open_pr and not args.increment:
        release.error("--open-pr requires a patch, minor or major increment")
    try:
        (release_plugin if args.mode == "release" else create_plugin)(args)
    except (ValueError, OSError, RuntimeError, plugin_zip.PackageError) as error:
        print(f"plugins {args.mode}: {error}", file=sys.stderr)
        ending("the workshop command stopped", "review the diagnostic above", f"/dev-plugin-{args.mode} {args.plugin}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
