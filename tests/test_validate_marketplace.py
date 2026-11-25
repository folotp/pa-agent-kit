"""Exercise the offline validator with a minimal Claude and Codex catalog."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate-marketplace.py"
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
SITE = "https://example.invalid"


class MarketplaceMetadataTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.script = self.root / "scripts/validate-marketplace.py"
        self.script.parent.mkdir()
        shutil.copyfile(SCRIPT, self.script)
        self.claude_path = self.root / ".claude-plugin/marketplace.json"
        self.codex_path = self.root / ".agents/plugins/marketplace.json"
        self.plugin_dir = self.root / "plugins/example"
        self.native_path = self.plugin_dir / ".claude-plugin/plugin.json"
        for path in (self.claude_path, self.codex_path, self.native_path):
            path.parent.mkdir(parents=True)
        self.native_path.symlink_to("../plugin.json")
        (self.plugin_dir / "README.md").write_text("# Example\n")
        (self.plugin_dir / "CHANGELOG.md").write_text("# Changelog\n")
        (self.root / "README.md").write_text("| [`example`](plugins/example/) | 0.1.0 |\n")
        self.author = {"name": "Maintainer", "url": f"{SITE}/maintainer"}
        self.entry = {
            "name": "example", "source": "./plugins/example", "description": "Example plugin",
            "category": "Productivity", "tags": ["example"],
        }
        self.claude = {
            "name": "example-marketplace", "description": "Example marketplace",
            "owner": self.author.copy(), "plugins": [self.entry],
        }
        self.codex = {
            "name": "example-marketplace", "interface": {"displayName": "Example Marketplace"},
            "plugins": [{
                "name": "example", "category": "Productivity",
                "source": {"source": "local", "path": "./plugins/example"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            }],
        }
        self.interface = {
            "displayName": "Example", "shortDescription": "Example subtitle",
            "longDescription": "Detailed example", "developerName": "Maintainer",
            "category": "Productivity", "websiteURL": f"{SITE}/example",
        }
        self.manifest = {
            "$schema": SCHEMA, "name": "example", "version": "0.1.0", "description": "Example plugin",
            "author": self.author, "homepage": f"{SITE}/example", "repository": f"{SITE}/source",
            "license": "MIT", "keywords": ["example"],
            "extensions": {"com.openai": {"interface": self.interface}},
        }

    def validate(self):
        for path, data in (
            (self.claude_path, self.claude), (self.codex_path, self.codex),
            (self.plugin_dir / "plugin.json", self.manifest),
        ):
            path.write_text(json.dumps(data))
        return subprocess.run([sys.executable, str(self.script)], capture_output=True, text=True)

    def assert_failure(self, *fields):
        result = self.validate()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for field in fields:
            self.assertIn(field, result.stdout)
        self.assertFalse(result.stderr, result.stderr)

    def test_private_plugin_passes_without_support_and_privacy_links(self):
        for explicit in (False, True):
            if explicit:
                self.entry["metadata"] = {"public": False}
            with self.subTest(explicit=explicit):
                result = self.validate()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_required_fields_across_both_catalogs_and_plugin(self):
        for obj, field, diagnostic in (
            (self.claude, "description", ".claude-plugin/marketplace.json.description"),
            (self.claude["owner"], "url", ".claude-plugin/marketplace.json.owner.url"),
            (self.codex["interface"], "displayName", ".agents/plugins/marketplace.json.interface.displayName"),
            (self.manifest, "$schema", "example/plugin.json.$schema"),
            (self.manifest, "homepage", "example/plugin.json.homepage"),
            (self.manifest, "license", "example/plugin.json.license"),
            (self.author, "url", "example/plugin.json.author.url"),
            (self.interface, "websiteURL", "example/plugin.json.extensions.com.openai.interface.websiteURL"),
        ):
            with self.subTest(field=diagnostic):
                value = obj.pop(field)
                try:
                    self.assert_failure(diagnostic)
                finally:
                    obj[field] = value

    def test_public_plugin_requires_links_on_each_listed_client(self):
        self.entry["metadata"] = {"public": True}
        self.assert_failure(
            "example/.claude-plugin/plugin.json.supportUrl",
            "example/.claude-plugin/plugin.json.privacyPolicyUrl",
            "example/plugin.json.extensions.com.openai.interface.supportURL",
            "example/plugin.json.extensions.com.openai.interface.privacyPolicyURL",
        )

    def test_public_plugin_passes_with_https_links(self):
        self.entry["metadata"] = {"public": True}
        self.native_path.unlink()
        self.native_path.write_text(json.dumps({
            "name": "example", "version": "0.1.0",
            "supportUrl": f"{SITE}/support", "privacyPolicyUrl": f"{SITE}/privacy",
        }))
        self.interface.update(supportURL=f"{SITE}/support", privacyPolicyURL=f"{SITE}/privacy")
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_public_must_be_boolean(self):
        self.entry["metadata"] = {"public": "false"}
        self.assert_failure("metadata.public")

    def test_codex_listing_must_match_claude_source(self):
        self.codex["plugins"][0]["source"]["path"] = "./plugins/other"
        self.assert_failure(".agents/plugins/marketplace.json.plugins[0].source")


if __name__ == "__main__":
    unittest.main()
