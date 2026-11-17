"""Build plugin zips from disposable git repositories: no network, no real tags."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "plugin_zip", Path(__file__).resolve().parents[1] / "scripts" / "plugin_zip.py")
pz = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pz
SPEC.loader.exec_module(pz)


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="plugin-zip-")
        self.repo = Path(self.tmp.name) / "repo"
        self.out = Path(self.tmp.name) / "out"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "Test")
        (self.repo / ".claude-plugin").mkdir()
        market = {"plugins": [{"name": "alpha", "source": "./plugins/alpha"},
                              {"name": "beta", "source": "./plugins/beta"}]}
        (self.repo / pz.MARKETPLACE).write_text(json.dumps(market))
        # alpha: no allowlist, one dev dir, one root manifest with a symlinked copy.
        self.put("plugins/alpha/plugin.json", json.dumps({"name": "alpha", "version": "1.2.3"}))
        (self.repo / "plugins/alpha/.claude-plugin").mkdir()
        (self.repo / "plugins/alpha/.claude-plugin/plugin.json").symlink_to("../plugin.json")
        self.put("plugins/alpha/skills/s/SKILL.md", "skill")
        self.put("plugins/alpha/.claude/settings.json", "{}")
        self.put("plugins/alpha/tests/t.py", "x")
        self.put("plugins/alpha/run.sh", "#!/bin/sh\n", mode=0o755)
        # beta: allowlist ships only skills/ and the manifest.
        self.put("plugins/beta/.claude-plugin/plugin.json",
                 json.dumps({"name": "beta", "version": "0.1.0"}))
        self.put("plugins/beta/skills/b/SKILL.md", "b")
        self.put("plugins/beta/notes.md", "private")
        self.put("plugins/beta/config/package-files.json",
                 json.dumps([".claude-plugin/plugin.json", "skills"]))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text, mode=0o644):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(mode)

    def names(self, archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            return archive.namelist()

    def test_default_selection_drops_development_files(self):
        path = pz.build(self.repo, "HEAD", "alpha", self.out)
        self.assertEqual(path.name, "alpha-v1.2.3.plugin")
        self.assertEqual(self.names(path), [".claude-plugin/plugin.json", "plugin.json",
                                            "run.sh", "skills/s/SKILL.md"])

    def test_symlink_is_stored_as_its_target_content(self):
        path = pz.build(self.repo, "HEAD", "alpha", self.out)
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(archive.read(".claude-plugin/plugin.json"),
                             archive.read("plugin.json"))

    def test_executable_bit_is_kept_and_modes_are_normalised(self):
        path = pz.build(self.repo, "HEAD", "alpha", self.out)
        with zipfile.ZipFile(path) as archive:
            modes = {i.filename: i.external_attr >> 16 for i in archive.infolist()}
        self.assertEqual(modes["run.sh"], 0o100755)
        self.assertEqual(modes["plugin.json"], 0o100644)

    def test_allowlist_limits_the_payload(self):
        path = pz.build(self.repo, "HEAD", "beta", self.out)
        self.assertEqual(self.names(path), [".claude-plugin/plugin.json", "skills/b/SKILL.md"])

    def test_allowlist_entry_that_does_not_exist_fails(self):
        self.put("plugins/beta/config/package-files.json", json.dumps(["skills", "missing"]))
        git(self.repo, "commit", "-q", "-am", "bad allowlist")
        with self.assertRaises(pz.PackageError):
            pz.build(self.repo, "HEAD", "beta", self.out)

    def test_two_builds_are_byte_identical_despite_file_times(self):
        first = pz.build(self.repo, "HEAD", "alpha", self.out / "one").read_bytes()
        (self.repo / "plugins/alpha/run.sh").touch()  # working-tree mtime must not matter
        second = pz.build(self.repo, "HEAD", "alpha", self.out / "two").read_bytes()
        self.assertEqual(first, second)

    def test_untracked_files_never_ship(self):
        self.put("plugins/alpha/skills/s/stray.md", "local only")
        path = pz.build(self.repo, "HEAD", "alpha", self.out)
        self.assertNotIn("skills/s/stray.md", self.names(path))

    def test_symlink_leaving_the_plugin_fails(self):
        (self.repo / "plugins/alpha/escape").symlink_to("../beta/notes.md")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "escape")
        with self.assertRaises(pz.PackageError):
            pz.build(self.repo, "HEAD", "alpha", self.out)

    def test_unknown_plugin_fails(self):
        with self.assertRaises(pz.PackageError):
            pz.build(self.repo, "HEAD", "gamma", self.out)


if __name__ == "__main__":
    unittest.main()
