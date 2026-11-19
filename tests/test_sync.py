"""Tests of `./dev sync` (tools/sync/sync.py) and of the drift check of `./dev check`.

The sync runs against a disposable workshop (a git repository holding a copy of the core and of the
script, so that its revisions are under the test's control) and a disposable consumer. The drift
tests run the real dispatcher of the synced consumer and need mise and the pinned tools, like
tests/test_dev.py. Nothing touches this repository.
"""

import contextlib
import hashlib
import importlib.util
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_dev import clean_env, run_dev

ROOT = Path(__file__).resolve().parent.parent
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=GIT_ENV, check=True).stdout


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sync-test."))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.workshop = self.tmp / "workshop"
        shutil.copytree(ROOT / "harness", self.workshop / "harness", ignore=shutil.ignore_patterns("__pycache__"))
        # A tracked file under harness/ that core.files does not name must never reach a consumer.
        (self.workshop / "harness" / "scripts").mkdir()
        (self.workshop / "harness" / "scripts" / "unlisted.py").write_text("print('not core')\n")
        (self.workshop / "tools" / "sync").mkdir(parents=True)
        shutil.copy2(ROOT / "tools" / "sync" / "sync.py", self.workshop / "tools" / "sync" / "sync.py")
        git(self.workshop, "init", "-q", "-b", "main")
        git(self.workshop, "add", "-A")
        git(self.workshop, "commit", "-q", "-m", "core")
        git(self.workshop, "tag", "harness-v0.1")
        self.consumer = self.tmp / "consumer"
        self.consumer.mkdir()
        git(self.consumer, "init", "-q", "-b", "main")
        (self.consumer / "README.md").write_text("consumer\n")
        git(self.consumer, "add", "-A")
        git(self.consumer, "commit", "-q", "-m", "init")

    def sync(self, *extra, target=None):
        return subprocess.run(
            ["python3", "-B", str(self.workshop / "tools" / "sync" / "sync.py"), "harness-v0.1", str(target or self.consumer), *extra],
            capture_output=True, text=True, env=GIT_ENV,
        )

    def test_copies_the_core_verbatim_with_checksums_in_one_commit(self):
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(git(self.consumer, "branch", "--show-current").strip(), "harness-sync/harness-v0.1")
        self.assertEqual(git(self.consumer, "rev-list", "--count", "main..HEAD").strip(), "1")
        for name in ("dev", "conf.awk", "gate", "guard", "core.files", "bindings/.claude/settings.json", "templates/AGENTS.shared.md"):
            self.assertEqual((self.consumer / ".harness" / name).read_bytes(), (ROOT / "harness" / name).read_bytes(), name)
        self.assertTrue(os.access(self.consumer / ".harness" / "dev", os.X_OK))
        self.assertFalse((self.consumer / ".harness" / "scripts").exists(), "a file core.files does not name is not core")
        lines = (self.consumer / ".harness" / "CHECKSUMS").read_text().splitlines()
        self.assertIn(f"755 {hashlib.sha256((ROOT / 'harness' / 'guard').read_bytes()).hexdigest()} guard", lines)
        self.assertIn(f"644 {hashlib.sha256((ROOT / 'harness' / 'conf.awk').read_bytes()).hexdigest()} conf.awk", lines)
        self.assertTrue(any(line.startswith("644 ") and line.endswith(" VERSION") for line in lines))
        self.assertTrue(any(line.endswith(" githooks/pre-push") and line.startswith("755 ") for line in lines))
        self.assertIn("commit ", (self.consumer / ".harness" / "VERSION").read_text())

    def test_files_are_read_by_the_resolved_commit(self):
        """Codex C6: after resolving <rev> once, no git call names it again, so a tag that moves
        during the run cannot give files that disagree with VERSION."""
        spec = importlib.util.spec_from_file_location("fixture_sync", self.workshop / "tools" / "sync" / "sync.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        calls, real_git = [], module.git
        module.git = lambda cwd, *args, **kw: calls.append(args) or real_git(cwd, *args, **kw)
        # In this process, so git takes its identity from os.environ (CI has no global one).
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.dict(os.environ, GIT_ENV):
            self.assertEqual(module.main(["harness-v0.1", str(self.consumer)]), 0)
        naming = [args for args in calls if any("harness-v0.1" in a for a in args)]
        self.assertTrue(naming and all(args[0] == "rev-parse" for args in naming[:1]), naming)
        self.assertEqual([a for a in naming if a[0] not in ("rev-parse", "switch", "commit")], [], naming)

    def test_differing_root_file_is_refused_unless_kept(self):
        """K22: a differing root file leaves part of the core unwired; sync says what, and stops."""
        (self.consumer / ".claude").mkdir()
        (self.consumer / ".claude" / "settings.json").write_text('{"own": true}\n')
        (self.consumer / "dev").write_text("#!/bin/sh\necho own dev\n")
        git(self.consumer, "add", "-A")
        git(self.consumer, "commit", "-q", "-m", "own settings and dev")
        refused = self.sync()
        self.assertEqual(refused.returncode, 1)
        self.assertIn(".claude/settings.json: the core guard hook for Claude Code would stay unwired", refused.stderr)
        self.assertIn("dev: the core dispatcher", refused.stderr)
        self.assertIn("--keep-root <file>", refused.stderr)
        self.assertEqual(git(self.consumer, "branch", "--list", "harness-sync/*").strip(), "", "nothing written")
        self.assertFalse((self.consumer / ".harness").exists())
        partly = self.sync("--keep-root", "dev")
        self.assertEqual(partly.returncode, 1)
        self.assertIn(".claude/settings.json", partly.stderr)
        self.assertNotIn("dev: the core dispatcher", partly.stderr)
        self.assertIn("names no root file", self.sync("--keep-root", "settings.json").stderr)

    def test_root_files_are_installed_only_where_absent_and_never_overwritten(self):
        (self.consumer / ".claude").mkdir()
        (self.consumer / ".claude" / "settings.json").write_text('{"own": true}\n')
        git(self.consumer, "add", "-A")
        git(self.consumer, "commit", "-q", "-m", "own settings")
        result = self.sync("--keep-root", ".claude/settings.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.consumer / ".claude" / "settings.json").read_text(), '{"own": true}\n')
        self.assertIn("`.claude/settings.json` DIFFERS from the core template; kept by --keep-root, so the core guard hook for Claude Code stays unwired", result.stdout)
        self.assertTrue((self.consumer / "dev").is_file() and os.access(self.consumer / "dev", os.X_OK))
        self.assertTrue((self.consumer / ".codex" / "hooks.json").is_file())
        self.assertIn("`.claude/skills` is not the symlink", result.stdout)

    def test_dependabot_template_is_written_only_when_absent(self):
        """24g D2: a starting point, never compared once the repository has its own."""
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.consumer / ".github" / "dependabot.yml").read_bytes(), (ROOT / "harness" / "templates" / "dependabot.yml").read_bytes())
        self.assertIn("`.github/dependabot.yml` written from `.harness/templates/dependabot.yml` (was absent)", result.stdout)

    def test_an_existing_dependabot_file_is_kept_and_reported(self):
        for name in ("dependabot.yml", "dependabot.yaml"):
            with self.subTest(name):
                self.setUp()
                own = self.consumer / ".github" / name
                own.parent.mkdir()
                own.write_text("version: 2\nupdates: []\n")
                git(self.consumer, "add", "-A")
                git(self.consumer, "commit", "-q", "-m", "own dependabot")
                result = self.sync()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(own.read_text(), "version: 2\nupdates: []\n")
                self.assertEqual(sorted(p.name for p in own.parent.iterdir()), [name])
                self.assertIn(f"`.github/{name}` kept as it is (the repository's own; `./dev check` judges", result.stdout)

    def test_agents_md_is_written_when_absent_with_the_shared_block_filled(self):
        """24g F1: without AGENTS.md no shared-block line reaches Codex or Antigravity."""
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (self.consumer / "AGENTS.md").read_text()
        block = (ROOT / "harness" / "templates" / "AGENTS.shared.md").read_text().strip("\n")
        self.assertIn(block, text)
        self.assertTrue(text.startswith("# Agent instructions\n"))
        self.assertIn("`AGENTS.md` written from `.harness/templates/AGENTS.md` (was absent)", result.stdout)
        self.assertIn("`AGENTS.md`: shared block replaced", result.stdout)
        self.assertNotIn("`CLAUDE.md` does not start with `@AGENTS.md`", result.stdout)

    def test_a_claude_md_that_does_not_import_agents_md_is_reported(self):
        (self.consumer / "CLAUDE.md").write_text("# Own rules\n")
        git(self.consumer, "add", "-A")
        git(self.consumer, "commit", "-q", "-m", "own claude")
        result = self.sync("--keep-root", "CLAUDE.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.consumer / "CLAUDE.md").read_text(), "# Own rules\n")
        self.assertIn("`CLAUDE.md` does not start with `@AGENTS.md`: Claude Code does not read `AGENTS.md`", result.stdout)

    def test_shared_block_is_replaced_between_markers_only(self):
        begin, end = "<!-- harness:shared:begin -->", "<!-- harness:shared:end -->"
        (self.consumer / "AGENTS.md").write_text(f"top\n{begin}\nold\n{end}\nown rules\n")
        git(self.consumer, "add", "-A")
        git(self.consumer, "commit", "-q", "-m", "agents")
        self.assertEqual(self.sync().returncode, 0)
        text = (self.consumer / "AGENTS.md").read_text()
        self.assertTrue(text.startswith("top\n" + begin) and text.endswith(end + "\nown rules\n"))
        self.assertNotIn("old", text)

    def test_refuses_a_dirty_target_the_workshop_itself_and_a_second_run(self):
        (self.consumer / "stray.txt").write_text("x")
        self.assertIn("uncommitted", self.sync().stderr)
        (self.consumer / "stray.txt").unlink()
        self.assertIn("workshop itself", self.sync(target=self.workshop).stderr)
        self.assertEqual(self.sync().returncode, 0)
        git(self.consumer, "switch", "-q", "main")
        self.assertIn("already exists", self.sync().stderr)
        git(self.consumer, "merge", "-q", "--ff-only", "harness-sync/harness-v0.1")
        git(self.consumer, "branch", "-q", "-d", "harness-sync/harness-v0.1")
        again = self.sync()
        self.assertEqual(again.returncode, 1)
        self.assertIn("nothing changed", again.stderr)
        self.assertEqual(git(self.consumer, "branch", "--list", "harness-sync/*").strip(), "", "failed run leaves no branch")
        self.assertEqual(git(self.consumer, "branch", "--show-current").strip(), "main")

    def synced_consumer_with_dispatcher(self):
        """Merge the sync branch, add the files a consumer owns, and return its environment."""
        self.assertEqual(self.sync().returncode, 0)
        (self.consumer / "harness.toml").write_text('profile = "plugin"\ntools = ["python3"]\n[checks]\nnone = "true"\n')
        for name in ("mise.toml", "mise.lock"):
            shutil.copy2(ROOT / name, self.consumer / name)
        return clean_env(hooks=".harness/githooks", MISE_TRUSTED_CONFIG_PATHS=str(self.consumer))

    def test_check_passes_on_a_clean_core_and_detects_every_kind_of_drift(self):
        env = self.synced_consumer_with_dispatcher()
        self.assertEqual(run_dev(self.consumer, "check", env=env).returncode, 0)
        guard = self.consumer / ".harness" / "guard"
        original = guard.read_bytes()
        guard.write_bytes(original + b"#")  # one byte
        result = run_dev(self.consumer, "check", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("differs from its CHECKSUMS: guard (content)", result.stderr)
        guard.write_bytes(original)
        (self.consumer / ".harness" / "extra.sh").write_text("echo hi\n")
        self.assertIn("does not list", run_dev(self.consumer, "check", env=env).stderr)
        (self.consumer / ".harness" / "extra.sh").unlink()
        (self.consumer / ".harness" / "link").symlink_to("guard")
        self.assertIn("does not list", run_dev(self.consumer, "check", env=env).stderr)
        (self.consumer / ".harness" / "link").unlink()
        guard.unlink()
        self.assertIn("guard (missing)", run_dev(self.consumer, "check", env=env).stderr)
        guard.write_bytes(original)  # back with the default mode, 644: not executable as recorded
        self.assertIn("guard (mode)", run_dev(self.consumer, "check", env=env).stderr)
        guard.chmod(0o755)
        self.assertEqual(run_dev(self.consumer, "check", env=env).returncode, 0)
        conf = self.consumer / ".harness" / "conf.awk"
        conf.chmod(0o755)
        self.assertIn("conf.awk (mode)", run_dev(self.consumer, "check", env=env).stderr)


if __name__ == "__main__":
    unittest.main()
