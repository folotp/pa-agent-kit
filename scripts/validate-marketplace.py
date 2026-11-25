#!/usr/bin/env python3
"""Check workshop marketplace metadata and portable plugin packages offline.

The Claude catalog defines the local plugin paths and public directory status.
Codex can list a subset of those packages. Root plugin.json owns each version,
which must also match the workshop README table.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
AGENTS_MARKETPLACE = REPO_ROOT / ".agents" / "plugins" / "marketplace.json"
README = REPO_ROOT / "README.md"

PORTABLE_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
PORTABLE_FIELDS = {
    "$schema", "name", "version", "description", "author", "homepage",
    "repository", "license", "keywords", "extensions",
}
PLUGIN_NAME = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
RELATIVE_SOURCE = re.compile(r"\./plugins/[A-Za-z0-9][A-Za-z0-9._-]*")
FORBIDDEN_ENTRY_FIELDS = ("version", "ref", "sha", "commit")


def read_object(path: Path) -> dict:
    """Read a JSON manifest and reject non-object roots."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def require_text(data: dict, fields: tuple[str, ...], label: str, errors: list[str]) -> None:
    for field in fields:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label}.{field}: expected non-empty text")


def require_https(data: dict, fields: tuple[str, ...], label: str, errors: list[str]) -> None:
    for field in fields:
        value = data.get(field)
        try:
            url = urlsplit(value) if isinstance(value, str) else None
            if (url and url.scheme == "https" and url.hostname and url.username is None
                    and not any(char.isspace() or ord(char) < 32 for char in value)):
                continue
        except ValueError:
            pass
        errors.append(f"{label}.{field}: expected an HTTPS URL without credentials")


def require_strings(data: dict, field: str, label: str, errors: list[str]) -> None:
    value = data.get(field)
    if (not isinstance(value, list) or not value
            or any(not isinstance(item, str) or not item.strip() for item in value)):
        errors.append(f"{label}.{field}: expected a non-empty list of strings")


def object_field(data: dict, field: str, label: str, errors: list[str]) -> dict:
    value = data.get(field)
    if isinstance(value, dict):
        return value
    errors.append(f"{label}.{field}: expected an object")
    return {}


def entries(data: dict, label: str, errors: list[str]) -> list[dict]:
    plugins = data.get("plugins")
    if not isinstance(plugins, list) or any(not isinstance(plugin, dict) for plugin in plugins):
        errors.append(f"{label}.plugins: expected a list of plugin objects")
        return []
    return plugins


def readme_version_for(plugin_name: str) -> str | None:
    """Return the version cell of the plugin's README table row, or None if absent."""
    match = re.search(
        r"^\|\s*\[\x60" + re.escape(plugin_name) + r"\x60\][^|]*\|\s*([^|]+?)\s*\|",
        README.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    return match.group(1).strip() if match else None


def plugin_manifest(plugin_dir: Path, name: str, public: bool, errors: list[str]) -> dict:
    """Check portable fields and the Claude manifest used for public directory links."""
    manifest_path = plugin_dir / "plugin.json"
    label = f"{name}/plugin.json"
    if manifest_path.is_symlink():
        errors.append(f"{label}: expected a regular root manifest")
        return {}
    try:
        manifest = read_object(manifest_path)
    except (OSError, ValueError) as exc:
        errors.append(f"{label}: {exc}")
        return {}

    for field in sorted(manifest.keys() - PORTABLE_FIELDS):
        errors.append(f"{label}.{field}: not a portable Agent Plugins field")
    if manifest.get("$schema") != PORTABLE_SCHEMA:
        errors.append(f"{label}.$schema: expected {PORTABLE_SCHEMA}")
    if manifest.get("name") != name or len(name) > 64 or not PLUGIN_NAME.fullmatch(name):
        errors.append(f"{label}.name: expected portable identifier matching the marketplace entry")
    require_text(manifest, ("version", "description", "license"), label, errors)
    require_https(manifest, ("homepage", "repository"), label, errors)
    require_strings(manifest, "keywords", label, errors)

    author = object_field(manifest, "author", label, errors)
    require_text(author, ("name",), f"{label}.author", errors)
    require_https(author, ("url",), f"{label}.author", errors)
    if author.keys() - {"name", "email", "url"} or (
        "email" in author and not isinstance(author["email"], str)
    ):
        errors.append(f"{label}.author: expected name, optional email and url strings")

    extensions = manifest.get("extensions", {})
    if not isinstance(extensions, dict) or any(not isinstance(value, dict) for value in extensions.values()):
        errors.append(f"{label}.extensions: expected an object of extension objects")
    for filename in ("README.md", "CHANGELOG.md"):
        path = plugin_dir / filename
        if not path.is_file() or not path.resolve().is_relative_to(plugin_dir.resolve()):
            errors.append(f"{name}/{filename}: required in the plugin directory")

    claude_path = plugin_dir / ".claude-plugin" / "plugin.json"
    claude_label = f"{name}/.claude-plugin/plugin.json"
    if not claude_path.is_file() or not claude_path.resolve().is_relative_to(plugin_dir.resolve()):
        errors.append(f"{claude_label}: required inside the plugin directory")
    elif public or claude_path.resolve() != manifest_path.resolve():
        try:
            claude_manifest = read_object(claude_path)
        except (OSError, ValueError) as exc:
            errors.append(f"{claude_label}: {exc}")
        else:
            for field in ("name", "version"):
                if field in claude_manifest and claude_manifest[field] != manifest.get(field):
                    errors.append(f"{claude_label}.{field}: conflicts with root plugin.json")
            if public:
                require_https(claude_manifest, ("supportUrl", "privacyPolicyUrl"), claude_label, errors)

    version = manifest.get("version")
    readme_version = readme_version_for(name)
    if readme_version is None:
        errors.append(f"{name}: no README plugins-table row found")
    elif isinstance(version, str) and version != readme_version:
        errors.append(f"{name}: README version cell {readme_version!r} != plugin.json {version!r}")
    return manifest


def public_status(entry: dict, label: str, errors: list[str]) -> bool:
    """An omitted setting means the plugin has no public directory submission."""
    metadata = entry.get("metadata", {})
    if not isinstance(metadata, dict) or not isinstance(metadata.get("public", False), bool):
        errors.append(f"{label}.metadata.public: expected a boolean when present")
        return False
    return metadata.get("public", False)


def check_claude(data: dict, errors: list[str]) -> dict[str, tuple[str, dict, bool]]:
    """Check the canonical catalog and return paths, manifests and directory status."""
    label = ".claude-plugin/marketplace.json"
    require_text(data, ("name", "description"), label, errors)
    owner = object_field(data, "owner", label, errors)
    require_text(owner, ("name",), f"{label}.owner", errors)
    require_https(owner, ("url",), f"{label}.owner", errors)
    plugins: dict[str, tuple[str, dict, bool]] = {}
    seen_sources = set()
    for index, entry in enumerate(entries(data, label, errors)):
        entry_label = f"{label}.plugins[{index}]"
        require_text(entry, ("name", "description", "category"), entry_label, errors)
        require_strings(entry, "tags", entry_label, errors)
        for field in FORBIDDEN_ENTRY_FIELDS:
            if field in entry:
                errors.append(f"{entry_label}.{field}: forbidden marketplace entry field")
        name, source = entry.get("name"), entry.get("source")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(source, str) or not RELATIVE_SOURCE.fullmatch(source):
            errors.append(f"{entry_label}.source: expected a './plugins/<dir>' string")
            continue
        if name in plugins or source in seen_sources:
            errors.append(f"{entry_label}: duplicate plugin name or source")
            continue
        plugin_dir = REPO_ROOT / source
        if not plugin_dir.is_dir() or plugin_dir.resolve() != plugin_dir:
            errors.append(f"{entry_label}.source: expected a local plugin directory at {source}")
            continue
        public = public_status(entry, entry_label, errors)
        plugins[name] = (source, plugin_manifest(plugin_dir, name, public, errors), public)
        seen_sources.add(source)
    return plugins


def check_codex(data: dict, plugins: dict[str, tuple[str, dict, bool]], errors: list[str]) -> None:
    """Check the Codex catalog and its listed plugins' presentation fields."""
    label = ".agents/plugins/marketplace.json"
    require_text(data, ("name",), label, errors)
    catalog_ui = object_field(data, "interface", label, errors)
    require_text(catalog_ui, ("displayName",), f"{label}.interface", errors)
    seen = set()
    for index, entry in enumerate(entries(data, label, errors)):
        entry_label = f"{label}.plugins[{index}]"
        require_text(entry, ("name", "category"), entry_label, errors)
        policy = object_field(entry, "policy", entry_label, errors)
        require_text(policy, ("installation", "authentication"), f"{entry_label}.policy", errors)
        for field in FORBIDDEN_ENTRY_FIELDS:
            if field in entry:
                errors.append(f"{entry_label}.{field}: forbidden marketplace entry field")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        if name in seen:
            errors.append(f"{entry_label}.name: duplicate plugin {name!r}")
            continue
        seen.add(name)
        if name not in plugins:
            errors.append(f"{entry_label}.name: {name!r} is absent from the Claude catalog")
            continue
        path, manifest, public = plugins[name]
        source = object_field(entry, "source", entry_label, errors)
        if source.get("source") != "local" or source.get("path") != path:
            errors.append(f"{entry_label}.source: expected a local source with path {path!r}")
        if not manifest:
            continue
        plugin_label = f"{name}/plugin.json"
        extensions = object_field(manifest, "extensions", plugin_label, errors)
        openai_label = f"{plugin_label}.extensions.com.openai"
        openai = object_field(extensions, "com.openai", f"{plugin_label}.extensions", errors)
        interface = object_field(openai, "interface", openai_label, errors)
        ui_label = f"{openai_label}.interface"
        require_text(interface, ("displayName", "shortDescription", "longDescription", "developerName", "category"),
                     ui_label, errors)
        require_https(interface, ("websiteURL",), ui_label, errors)
        if public:
            require_https(interface, ("supportURL", "privacyPolicyURL"), ui_label, errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true",
                        help="accepted for compatibility; checks never use the network")
    parser.parse_args()
    errors: list[str] = []
    try:
        claude = read_object(MARKETPLACE)
        codex = read_object(AGENTS_MARKETPLACE)
        plugins = check_claude(claude, errors)
        check_codex(codex, plugins, errors)
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    if errors:
        print("validate-marketplace: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("validate-marketplace: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
