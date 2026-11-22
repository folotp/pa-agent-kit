#!/usr/bin/env python3
"""Check workshop instructions for unnamed operator steps and stale repository paths."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
PA_STEP = re.compile(
    r"\bgh-token\.sh owner --|\btag-release\.py\b|--draft=false\b|\bdraft=false\b"
    r"|\bgit branch -D\b|\bgit pull\b|\bcodex exec\b|\bgh workflow run\b"
)
DEV_COMMAND = re.compile(r"(?<![\w:/])(?:/|\$)dev-[a-z0-9]+(?:-[a-z0-9]+)*\b")
SPAN = re.compile(r"\x60+([^\x60\n]+)\x60+")
LINK = re.compile(r"\]\((<[^>]+>|[^)\s]+)(?:\s+[^)]*)?\)")
IMPORT = re.compile(r"^@([^\s]+)")
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")
PATH_TOKEN = re.compile(r"(?:[.\w-]+/)*[.\w-]+/?$")
LIST_ITEM = re.compile(r"^\s*(?:[-*+] |\d+\. )")
REPO_FILE = re.compile(r"\.(?:md|py|sh|awk|json|toml|ya?ml|lock)$")
CONSUMER = ".harness"
EXTERNAL_ROOTS = {".git", ".obsidian", "refs", "repos"}
# Tool-protocol and Markdown syntax examples in the packaged skill instructions.
NON_FILE_EXAMPLES = {"tools/list_changed", "url"}
OWNER_DOC = ROOT / "harness/gh-token.md"



def docs_issues(path):
    # Commands in a fenced block belong to its introductory paragraph. A blank
    # line before the fence is conventional Markdown and does not split the step.
    content = path.read_text()
    # This tagged core guide names its owner-token skill once for all recipes.
    owner_guide = path.absolute() == OWNER_DOC and "/dev-run-with-owner-token" in content
    paragraph = []
    fenced = False

    def problems(lines):
        if lines and not DEV_COMMAND.search("\n".join(line for _, line in lines)):
            for number, line in lines:
                match = PA_STEP.search(line)
                if match and not (owner_guide and match[0].startswith("gh-token.sh owner")):
                    yield number, f"operator step '{match[0]}' needs its /dev- command"

    for number, line in enumerate(content.splitlines(), 1):
        if line.lstrip().startswith(("\x60\x60\x60", "~~~")):
            fenced = not fenced
            paragraph.append((number, line))
        elif not fenced and not line.strip():
            if paragraph and paragraph[-1][1]:
                paragraph.append((number, ""))
        elif not fenced and paragraph and (
            not paragraph[-1][1] or LIST_ITEM.match(line)
            or (line.startswith("|") and paragraph[-1][1].startswith("|"))
        ):
            # A stand-alone example may be named by the very next paragraph.
            standalone_example = paragraph[0][1].lstrip().startswith(("\x60\x60\x60", "~~~"))
            if standalone_example and line and line[0].isalpha():
                paragraph.append((number, line))
                continue
            yield from problems(paragraph)
            paragraph = [(number, line)]
        else:
            paragraph.append((number, line))
    yield from problems(paragraph)


def instruction_files(root):
    # Use git's inventory so installed caches and ignored local files are never read.
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
         "--", "AGENTS.md", "CLAUDE.md", ":(glob)**/AGENTS.md",
         ":(glob)**/CLAUDE.md", ":(glob)**/SKILL.md"], cwd=root, text=True
    )
    return sorted({root / path for path in paths.split("\0") if path and (root / path).is_file()})


def cited_paths(line, known_names):
    """Read Markdown links, imports, and literal repo paths inside code spans."""
    for match in LINK.finditer(line):
        target = match[1].strip("<>")
        parsed = urlsplit(target)
        if parsed.path and not parsed.scheme and not parsed.netloc and not target.startswith("#"):
            yield unquote(parsed.path), True
    match = IMPORT.match(line)
    if match:
        yield match[1], True

    # URLs, shell placeholders and globs within code refer to patterns, not files.
    for match in SPAN.finditer(line):
        text = match[1].strip()
        if "://" in text or text.startswith(("~/", "/", "$", "<")):
            continue
        if " " in text and not text.startswith(("python", "bash ", "sh ", "git ", "gh ", "./")):
            continue
        for word in text.split():
            literal = word.strip("(),")
            prefix = literal.partition("/")[0]
            if not PATH_TOKEN.fullmatch(literal):
                continue
            if (literal.startswith(("./", "../")) or literal == CONSUMER
                    or ("/" in literal and (prefix in known_names or REPO_FILE.search(literal)))
                    or (literal == text and REPO_FILE.search(literal)
                        and (literal in known_names or path_is_root_name(literal)))):
                yield literal, False


def path_is_root_name(literal):
    return "/" not in literal and literal in {"AGENTS.md", "CLAUDE.md", "README.md", "SKILL.md"}


def path_issues(path, root):
    relative = path.relative_to(root)
    physical_root = root.resolve()
    # Plugin instructions and skills often cite package-relative paths. A named
    # sibling skill can provide a reference explicitly scoped to that skill.
    scopes = [path.parent, root]
    plugin = None
    if relative.parts[0] == "plugins" and len(relative.parts) > 2:
        plugin = root / "plugins" / relative.parts[1]
        scopes.insert(1, plugin)
    entries = {entry.name: entry for scope in scopes for entry in scope.iterdir()}

    for number, line in enumerate(path.read_text().splitlines(), 1):
        for citation, is_link in dict.fromkeys(cited_paths(line, entries)):
            if (citation in NON_FILE_EXAMPLES or citation.split("/")[0] in EXTERNAL_ROOTS
                    or citation.startswith("~")):
                continue
            if citation == CONSUMER or citation.startswith(CONSUMER + "/"):
                locations = [root / "harness" / citation.removeprefix(CONSUMER).lstrip("/")]
            elif citation.startswith("/"):
                locations = [root / citation.lstrip("/")]
            elif is_link:
                locations = [path.parent / citation]
            elif citation.startswith("../"):
                locations = [path.parent / citation]
                if path == root / "CLAUDE.md" and ".claude/skills" in line:
                    locations.append(root / ".claude" / citation)
            else:
                locations = [scope / citation for scope in scopes]
                if plugin and citation.startswith("references/"):
                    locations.extend(plugin / "skills" / match[1] / citation for match in SPAN.finditer(line)
                                     if NAME.fullmatch(match[1]) and match[1] != path.parent.name)
            if not any(location.exists() and location.resolve().is_relative_to(physical_root)
                       for location in locations):
                yield number, f"repository path does not exist: {citation}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check-docs", "check-paths"))
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    if args.mode == "check-docs":
        sources = [path for arg in args.paths
                   for path in (sorted(arg.rglob("*.md")) if arg.is_dir() else [arg])]
        check = docs_issues
    else:
        sources = [path.absolute() for path in args.paths] or instruction_files(ROOT)
        check = lambda path: path_issues(path, ROOT)

    failed = False
    for path in sources:
        for line, message in check(path):
            print(f"{path.absolute().relative_to(ROOT)}:{line}: {message}")
            failed = True
    if not failed:
        print(f"{args.mode}: OK ({len(sources)} files)")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
