"""Exercise workshop commands with local Git fixtures and a mocked GitHub API."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/workshop"))
import check_docs  # noqa: E402
import plugins  # noqa: E402


class DocCheckTests(unittest.TestCase):
    def test_each_operator_step_needs_its_own_command(self):
        with tempfile.TemporaryDirectory() as directory:
            doc = Path(directory) / "docs.md"
            doc.write_text(
                "1. Use /dev-plugin-release.\n\n"
                "   \x60\x60\x60sh\n   python3 scripts/tag-release.py example\n   \x60\x60\x60\n"
                "2. Publish using " + "\x60gh api -F draft=" + "false\x60.\n"
            )
            self.assertEqual([line for line, _ in check_docs.docs_issues(doc)], [6])
            doc.write_text(doc.read_text().replace("2. Publish", "2. Use /dev-plugin-release to publish"))
            self.assertEqual(list(check_docs.docs_issues(doc)), [])

    def test_stale_link_and_cited_workshop_path_name_the_missing_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tools").mkdir()
            (root / "tools/current.py").touch()
            doc = root / "AGENTS.md"
            doc.write_text(
                "Run \x60python3 tools/current.py\x60.\n"
                "Run \x60python3 tools/missing.py\x60.\n"
                "See [the guide](docs/missing.md) and [upstream](https://example.org/docs/).\n"
            )
            self.assertEqual(list(check_docs.path_issues(doc, root)), [
                (2, "repository path does not exist: tools/missing.py"),
                (3, "repository path does not exist: docs/missing.md"),
            ])

    def test_toolkit_package_excludes_retired_release_skill_and_executor(self):
        plugin = ROOT / "plugins/pa-toolkit"
        inventory = json.loads((plugin / "config/package-files.json").read_text())
        self.assertFalse(any("plugin-release" in path for path in inventory))
        self.assertFalse((plugin / "skills/plugin-release/SKILL.md").exists())
        self.assertFalse((plugin / "agents/plugin-release-executor.md").exists())

    def test_new_commands_appear_once(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, "HOME": directory, "GH_CONFIG_DIR": directory}
            listing = subprocess.check_output(["harness/commands", "list"], cwd=ROOT,
                                              text=True, env=env)
        for command in ("dev-plugin-create", "dev-plugin-release"):
            with self.subTest(command=command):
                self.assertEqual(listing.count(f"  /{command} — "), 1)


class CreateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.repo = root / "workshop"
        self.marketplace = self.repo / ".claude-plugin/marketplace.json"
        self.marketplace.parent.mkdir(parents=True)
        (self.repo / ".agents/plugins").mkdir(parents=True)
        (self.repo / "plugins/example").mkdir(parents=True)
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts/validate-marketplace.py").write_bytes(
            (ROOT / "scripts/validate-marketplace.py").read_bytes()
        )
        (self.repo / ".agents/plugins/marketplace.json").write_text('{"plugins":[]}\n')
        (self.repo / "plugins/example/plugin.json").write_text('{"name":"example","version":"0.1.0"}\n')
        self.marketplace.write_text(
            '{\n  "plugins": [\n    {"name":"example","source":"./plugins/example","tags": ["one", "two"]}\n  ]\n}\n'
        )
        (self.repo / "README.md").write_text("| [\x60example\x60](plugins/example/) | 0.1.0 | in-repo | Existing |\n")
        self.git("init", "-q", "-b", "main", repo=self.repo)
        self.git("add", ".", repo=self.repo)
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "fixture", repo=self.repo)
        self.worktree = root / "feature"
        self.git("worktree", "add", "-qb", "feat/create", str(self.worktree), repo=self.repo)

    def git(self, *args, repo):
        return subprocess.check_output(["git", *args], cwd=repo, text=True)

    def test_dry_run_and_scaffold(self):
        args = SimpleNamespace(plugin="new-plugin", description='One "line" of text', category="tools",
                               tags="one,two", version="0.1.0", component="skills", dry_run=True)
        with contextlib.redirect_stdout(io.StringIO()):
            plugins.create_plugin(args, self.worktree)
            self.assertEqual(self.git("status", "--porcelain", repo=self.worktree), "")
            args.dry_run = False
            plugins.create_plugin(args, self.worktree)
        marketplace = (self.worktree / plugins.CLAUDE_MARKETPLACE).read_text()
        self.assertIn('"tags": ["one", "two"]}', marketplace)
        entry = json.loads(marketplace)["plugins"][-1]
        self.assertEqual(entry["source"], "./plugins/new-plugin")
        self.assertNotIn("version", entry)
        self.assertTrue((self.worktree / "plugins/new-plugin/skills/new-plugin/SKILL.md").is_file())
        self.assertFalse((self.repo / "plugins/new-plugin").exists())
        with self.assertRaisesRegex(ValueError, "already exists"):
            plugins.create_plugin(args, self.worktree)


    def test_bump_pr_uses_one_version_branch_and_retries_after_a_push_failure(self):
        self.git("config", "user.name", "Fixture", repo=self.repo)
        self.git("config", "user.email", "fixture@example.invalid", repo=self.repo)
        sha = self.git("rev-parse", "HEAD", repo=self.repo).strip()
        args = SimpleNamespace(plugin="example", bot="codex")
        calls = []
        real_run = plugins.run
        fail_first_push = True

        def fake_run(*command, **kwargs):
            if command[0] == "./dev":
                calls.append(command[:2])
                return ""
            return real_run(*command, **kwargs)

        def bot(bot_name, *command, repo):
            nonlocal fail_first_push
            self.assertEqual(bot_name, "codex")
            calls.append(command[:2])
            if command[:2] == ("git", "commit"):
                return self.git(*command[1:], repo=repo)
            if command[:2] == ("git", "push"):
                self.assertEqual(command[2:], ("origin", "HEAD:refs/heads/bump/example-0.1.1"))
                if fail_first_push:
                    fail_first_push = False
                    raise RuntimeError("fixture push failure")
                return ""
            self.assertEqual(command[:3], ("gh", "pr", "create"))
            return "https://example.invalid/pull/1"

        with mock.patch.object(plugins, "run", side_effect=fake_run), \
                mock.patch.object(plugins, "as_bot", side_effect=bot), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "fixture push failure"):
                plugins.submit_bump(args, self.repo, sha, "plugins/example", "0.1.0", "0.1.1")
            plugins.submit_bump(args, self.repo, sha, "plugins/example", "0.1.0", "0.1.1")
        self.assertEqual(calls, [
            ("./dev", "check"), ("git", "commit"), ("./dev", "ci"), ("git", "push"),
            ("./dev", "ci"), ("git", "push"), ("gh", "pr"),
        ])


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(plugin="example", bot="codex", increment=None, open_pr=None)
        self.tag = "example/v1.2.0"
        self.sha = "a" * 40

    def inspect(self, tagged=True, release=None, pr=None, increment=None, needs_bump=False):
        self.args.increment = increment
        pr_response = [{"headRefName": "bump/example-1.2.0", "url": pr, "files": []}] if pr else []
        fake_run = mock.Mock(return_value=self.sha)

        def bot(bot_name, *command, **kwargs):
            self.assertEqual(bot_name, "codex")
            if command == plugins.release_plugins.RELEASE_LIST:
                return json.dumps([[], [release] if release else []])
            if command[:3] == ("gh", "pr", "list"):
                return json.dumps(pr_response)
            self.fail(f"unexpected mutation or lookup {command}")

        output = io.StringIO()
        with (
            mock.patch.object(plugins.subprocess, "run", return_value=mock.Mock(returncode=1)),
            mock.patch.object(plugins, "run", fake_run),
            mock.patch.object(plugins, "as_bot", side_effect=bot),
            mock.patch.object(plugins.plugin_zip, "marketplace_path", return_value="plugins/example"),
            mock.patch.object(plugins.release_plugins, "version_at", return_value="1.2.0"),
            mock.patch.object(plugins.release_plugins, "release_for_tag"),
            mock.patch.object(plugins.plugin_zip, "collect", return_value=({}, "", ["skills/dummy/SKILL.md"], {})),
            mock.patch.object(plugins.tag_release, "remote_tag_names", return_value={self.tag} if tagged else set()),
            mock.patch.object(plugins.tag_release, "plan_tag", return_value=(self.tag, self.sha),
                              side_effect=plugins.tag_release.BumpRequired if needs_bump else None),
            contextlib.redirect_stdout(output),
        ):
            plugins.release_plugin(self.args)
        return output.getvalue()

    def test_waits_for_existing_pr_instead_of_creating_another(self):
        output = self.inspect(tagged=False, pr="https://example.invalid/pull/1")
        self.assertIn("https://example.invalid/pull/1", output)
        self.assertNotIn("github-owner-token", output)

    def test_tag_instruction_is_single_owner_operation_bound_to_dry_run_commit(self):
        output = self.inspect(tagged=False)
        self.assertIn(f"--expect-commit {self.sha}", output)
        self.assertIn("Keychain dialog for github-owner-token", output)

    def test_untaggable_plugin_version_can_start_a_new_bump(self):
        output = self.inspect(tagged=False, needs_bump=True, increment="patch")
        self.assertIn("planned example 1.2.0 to 1.2.1", output)
        self.assertNotIn("github-owner-token", output)

    def test_incomplete_draft_cannot_be_published(self):
        output = self.inspect(release={"tag_name": self.tag, "draft": True, "assets": []})
        self.assertIn("dummy.zip", output)
        self.assertNotIn("PATCH", output)

    def test_publish_instruction_uses_id_and_tag_after_assets(self):
        assets = [{"name": name, "state": "uploaded", "size": 1}
                  for name in ("example-v1.2.0.plugin", "dummy.zip")]
        output = self.inspect(release={"tag_name": self.tag, "id": 123, "draft": True, "assets": assets})
        self.assertIn("releases/123", output)
        self.assertIn(f"tag_name={self.tag}", output)
        self.assertIn("draft=" + "false", output)

    def test_published_release_offers_refresh_or_bump(self):
        release = {"tag_name": self.tag, "draft": False, "immutable": True}
        self.assertIn("codex plugin marketplace upgrade", self.inspect(release=release))
        self.assertIn("planned example 1.2.0 to 1.3.0", self.inspect(release=release, increment="minor"))


if __name__ == "__main__":
    unittest.main()
