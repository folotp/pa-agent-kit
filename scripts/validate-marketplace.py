#!/usr/bin/env python3
"""Validate the marketplace manifests against the plugin trees in this repo.

Every plugin is listed by relative path, so the manifests and the plugin
trees travel in one commit and the check needs no network. It verifies:
  - the Claude Code manifest parses and every entry's `source` is a
    `./plugins/<dir>` string naming an existing directory (no cross-repository
    sources, no `..`, no pins: `ref`, `sha`, `commit`)
  - no entry carries a top-level `version` (plugin.json is the only source)
  - each plugin directory has a plugin.json (root, or `.claude-plugin/`) whose
    `name` matches the entry and whose `version` is non-empty
  - the README plugins table has a row for each entry with the same version
  - the Codex manifest (`.agents/plugins/marketplace.json`) lists only plugins
    that the Claude Code manifest lists, with `{"source": "local", "path": ...}`
    pointing at the same directory

Exits non-zero on any failure. Stdlib only. `--offline` is accepted and ignored
(kept so the PostToolUse hook and CI invocations do not change).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
AGENTS_MARKETPLACE = REPO_ROOT / ".agents" / "plugins" / "marketplace.json"
README = REPO_ROOT / "README.md"

RELATIVE_SOURCE = re.compile(r"^\./plugins/[A-Za-z0-9][A-Za-z0-9._-]*$")
FORBIDDEN_ENTRY_FIELDS = ("version", "ref", "sha", "commit")


def plugin_manifest(plugin_dir: Path) -> dict:
    """Return the plugin's manifest: root plugin.json first, then the Claude path.

    Raises FileNotFoundError when neither exists and ValueError on invalid JSON."""
    for candidate in (plugin_dir / "plugin.json", plugin_dir / ".claude-plugin" / "plugin.json"):
        if candidate.is_file():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{candidate.relative_to(REPO_ROOT)} does not parse: {exc}")
    raise FileNotFoundError("no plugin.json or .claude-plugin/plugin.json")


def readme_version_for(plugin_name: str) -> str | None:
    """Return the version cell of the plugin's README table row, or None if absent."""
    text = README.read_text(encoding="utf-8")
    match = re.search(
        r"^\|\s*\[`" + re.escape(plugin_name) + r"`\][^|]*\|\s*([^|]+?)\s*\|",
        text,
        flags=re.MULTILINE,
    )
    return match.group(1).strip() if match else None


def check_claude_entries(data: dict) -> tuple[list[str], dict[str, str]]:
    """Validate the Claude Code manifest; return (errors, {name: source path})."""
    errors: list[str] = []
    sources: dict[str, str] = {}
    for entry in data.get("plugins", []):
        name = entry.get("name", "<unnamed>")
        for field in FORBIDDEN_ENTRY_FIELDS:
            if field in entry:
                errors.append(f"{name}: forbidden top-level '{field}' field")
        source = entry.get("source")
        if not isinstance(source, str) or not RELATIVE_SOURCE.match(source):
            errors.append(f"{name}: source must be a './plugins/<dir>' string, got {source!r}")
            continue
        sources[name] = source
        plugin_dir = REPO_ROOT / source
        if not plugin_dir.is_dir():
            errors.append(f"{name}: source directory {source} does not exist")
            continue
        try:
            manifest = plugin_manifest(plugin_dir)
        except (FileNotFoundError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
            continue
        if manifest.get("name") != name:
            errors.append(f"{name}: plugin.json name is {manifest.get('name')!r}")
        version = manifest.get("version")
        if not version:
            errors.append(f"{name}: plugin.json has no version")
        readme_version = readme_version_for(name)
        if readme_version is None:
            errors.append(f"{name}: no README plugins-table row found")
        elif version and readme_version != version:
            errors.append(f"{name}: README version cell '{readme_version}' != plugin.json '{version}'")
    return errors, sources


def check_codex_entries(agents_data: dict, claude_sources: dict[str, str]) -> list[str]:
    """Each Codex entry must match a Claude Code entry and use a local source."""
    errors: list[str] = []
    for entry in agents_data.get("plugins", []):
        name = entry.get("name")
        source = entry.get("source")
        if name not in claude_sources:
            errors.append(f"{name}: in .agents marketplace but not the Claude one")
        elif not isinstance(source, dict) or source.get("source") != "local":
            errors.append(f"{name}: .agents source must be {{'source': 'local', 'path': ...}}")
        elif source.get("path") != claude_sources[name]:
            errors.append(f"{name}: .agents path {source.get('path')!r} != {claude_sources[name]!r}")
    return errors


def main() -> int:
    """Run all checks, print every failure, return nonzero if any. Read-only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true",
                        help="accepted for compatibility; checks never use the network")
    parser.parse_args()
    try:
        data = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
        agents_data = json.loads(AGENTS_MARKETPLACE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"FAIL: a marketplace manifest does not parse: {exc}")
        return 1
    errors, sources = check_claude_entries(data)
    errors += check_codex_entries(agents_data, sources)
    if errors:
        print("validate-marketplace: FAIL")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("validate-marketplace: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
