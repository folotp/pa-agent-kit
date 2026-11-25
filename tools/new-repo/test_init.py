"""Provisioning contracts exercised against disposable Git checkouts."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSHOP = HERE.parents[1]


def file_state(root):
    """Compare bytes, modes and mtime to catch a rewrite of otherwise identical data."""
    return {
        path.relative_to(root): (
            path.lstat().st_mode,
            path.lstat().st_mtime_ns,
            os.readlink(path) if path.is_symlink() else path.read_bytes(),
        )
        for path in root.rglob("*")
        if path.is_symlink() or path.is_file()
    }


class InitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Actions checks out a shallow branch. Make the release fixture independent of local tags.
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        workshop = Path(temp.name)
        shutil.copytree(WORKSHOP / "harness", workshop / "harness", symlinks=True)
        shutil.copytree(WORKSHOP / "tools/sync", workshop / "tools/sync")
        shutil.copytree(HERE, workshop / "tools/new-repo")
        shutil.copyfile(WORKSHOP / "mise.lock", workshop / "mise.lock")
        cls.init_script = workshop / "tools/new-repo/init.py"

        def git(*args):
            subprocess.run(["git", "-C", str(workshop), *args], check=True, capture_output=True)

        bump = workshop / "harness/templates/mise-bump.yml"
        bump_template = bump.read_bytes()
        bump.unlink()
        git("init", "-q", "-b", "main")
        git("config", "user.name", "Test")
        git("config", "user.email", "test@example.invalid")
        git("add", "harness")
        git("commit", "-qm", "core fixture")
        git("tag", "harness-v1.0")
        bump.write_bytes(bump_template)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q", "-b", "main")
        self.git("remote", "add", "origin", "https://github.com/example-owner/example-repo.git")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True)

    def provision(self, *args, profile="plain", env=None):
        return subprocess.run(
            [sys.executable, "-B", str(self.init_script), str(self.root), "--profile", profile, *args],
            capture_output=True, text=True, env=env,
        )

    def test_dry_run_neither_calls_external_tools_nor_writes_in_a_read_only_clone(self):
        with tempfile.TemporaryDirectory() as bin_dir:
            tools = Path(bin_dir)
            sentinel = tools / "called"
            git = shutil.which("git")
            (tools / "git").symlink_to(git)
            for command in ("gh", "mise", "curl"):
                stub = tools / command
                stub.write_text(f"#!/bin/sh\ntouch '{sentinel}'\nexit 42\n", encoding="utf-8")
                stub.chmod(0o755)
            env = {"PATH": bin_dir}
            before = file_state(self.root)
            self.root.chmod(0o555)
            self.addCleanup(self.root.chmod, 0o755)
            result = self.provision("--dry-run", env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("harness-v", result.stdout)
            self.assertIn("mise-bump.yml", result.stdout)
            self.assertFalse(sentinel.exists())
            self.assertEqual(file_state(self.root), before)

    def test_scaffold_writes_released_core_and_is_idempotent_before_owner_push(self):
        args = ("--tag", "harness-v1.0", "--defer-hooks")
        first = self.provision(*args)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual((self.root / ".github/CODEOWNERS").read_text(), "* @example-owner\n")
        self.assertIn("mise-bump", (self.root / ".github/dependabot.yml").read_text())
        self.assertTrue((self.root / ".github/workflows/mise-bump.yml").is_file())
        self.assertTrue(os.access(self.root / ".harness/githooks/pre-push", os.X_OK))
        self.assertEqual(os.readlink(self.root / ".claude/skills"), "../.agents/skills")
        self.assertEqual((self.root / ".github/workflows/ci.yml").read_bytes(),
                         (self.root / ".harness/templates/ci.yml").read_bytes())
        self.assertNotIn('gh = ', (self.root / "mise.toml").read_text())
        before = file_state(self.root)
        second = self.provision(*args)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("0 new files or links", second.stdout)
        self.assertEqual(file_state(self.root), before)

    def test_live_adds_empty_gate_fields_and_locked_gh(self):
        result = self.provision("--defer-hooks", profile="live")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('# [gate]\n# repo = ""\n# merger = ""\n', (self.root / "harness.toml").read_text())
        self.assertIn("[[tools.gh]]", (self.root / "mise.lock").read_text())

    def test_collision_does_not_install_anything(self):
        codeowners = self.root / ".github/CODEOWNERS"
        codeowners.parent.mkdir()
        codeowners.write_text("Existing ownership information\n")
        before = file_state(self.root)
        result = self.provision("--defer-hooks")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CODEOWNERS differs", result.stderr)
        self.assertEqual(file_state(self.root), before)

    def test_refuses_redirected_parent_without_following_it(self):
        with tempfile.TemporaryDirectory() as external:
            (self.root / ".github").symlink_to(external)
            result = self.provision("--defer-hooks")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("existing path at .github", result.stderr)
            self.assertEqual(list(Path(external).iterdir()), [])
            self.assertFalse((self.root / ".harness").exists())

    def test_deferral_never_disables_active_hook_configuration(self):
        self.git("config", "core.hooksPath", ".harness/githooks")
        before = file_state(self.root)
        result = self.provision("--defer-hooks")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("leave them active", result.stderr)
        self.assertEqual(file_state(self.root), before)


if __name__ == "__main__":
    unittest.main()
