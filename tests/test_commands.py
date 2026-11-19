"""Tests of harness/commands, the index behind /dev-help and /dev-status (24g row I4).

Each test builds a consumer in a scratch directory: `.harness/` holding the index, the prune script,
conf.awk and a few skills; repository skills and commands; a scratch HOME with plugin caches and
user skills; a stub `gh`; and a bare repository standing in for the public workshop's tags.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "harness"

# The stub answers from files named by the environment; each file already holds the --jq result.
GH_STUB = """#!/usr/bin/env bash
case "$1 $2" in
  "auth status") [ -n "${GH_LOGGED_IN:-}" ] ;;
  "pr list")
    for a in "$@"; do [ "$a" = merged ] && { head=""; while [ $# -gt 0 ]; do [ "$1" = --head ] && head="$2"; shift; done
      awk -v h="$head" '$1==h{print $2" "$3}' "$GH_MERGED"; exit 0; }; done
    cat "$GH_OPEN_PRS" ;;
  "release list") cat "$GH_RELEASES" ;;
  *) echo "stub gh: unexpected $*" >&2; exit 1 ;;
esac
"""


def skill(name, description="Does a thing.", extra=""):
    return f"---\nname: {name}\ndescription: {description}\n{extra}---\n\nBody.\n"


class CommandsTest(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="commands-test."))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.home = self.work / "home"
        self.home.mkdir()
        bin_dir = self.work / "bin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text(GH_STUB)
        (bin_dir / "gh").chmod(0o755)
        for name in ("merged", "open_prs", "releases"):
            (self.work / name).write_text("")
        self.env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(self.home),
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "GH_MERGED": str(self.work / "merged"), "GH_OPEN_PRS": str(self.work / "open_prs"),
            "GH_RELEASES": str(self.work / "releases"),
        }
        self.repo = self.work / "repo"
        core = self.repo / ".harness"
        (core / "skills").mkdir(parents=True)
        for name in ("commands", "harness-sync", "git-prune-merged.sh", "conf.awk"):
            shutil.copy2(HARNESS / name, core / name)
        self.write(".harness/skills/dev-help/SKILL.md", skill("dev-help", "Lists every dev- command."))
        self.write(".harness/skills/dev-run-ci-locally/SKILL.md",
                   skill("dev-run-ci-locally", "Runs the checks.", "metadata:\n  audience: agents\n"))
        (core / "VERSION").write_text("core harness-v1.0\ncommit 0\n")
        self.write("harness.toml", 'profile = "plugin"\ntools = ["git"]\n')
        self.git("init", "-q", "-b", "main")
        self.git("config", "core.hooksPath", ".harness/githooks")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")
        self.git("remote", "add", "origin", "https://github.com/example/demo.git")
        # The workshop's tags, in a bare repository.
        self.workshop = self.work / "workshop.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.workshop)], env=self.env, check=True)
        self.env["HARNESS_WORKSHOP_URL"] = str(self.workshop)

    def write(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def run_commands(self, *args, **extra_env):
        result = subprocess.run([str(self.repo / ".harness" / "commands"), *args], cwd=self.repo,
                                env={**self.env, **extra_env}, capture_output=True, text=True, timeout=60)
        self.out = result.stdout
        self.err = result.stderr
        self.lines = result.stdout.splitlines()
        return result.returncode

    def group(self, title):
        """The lines under one heading of `list`."""
        start = self.lines.index(title) + 1
        body = []
        for line in self.lines[start:]:
            if not line.startswith("  "):
                break
            body.append(line.strip())
        return body

    # --- list

    def test_list_groups_every_place(self):
        self.write(".agents/skills/dev-repo-thing/SKILL.md", skill("dev-repo-thing", "Repository thing."))
        os.symlink("../../.harness/skills/dev-help", self.repo / ".agents/skills/dev-help")  # a core link
        self.write(".claude/commands/dev-old.md", "---\ndescription: An old command.\n---\nBody\n")
        for version in ("1.0.0", "1.1.0"):  # two cached versions, one line
            p = self.home / f".claude/plugins/cache/market/tools/{version}/skills/dev-plug/SKILL.md"
            p.parent.mkdir(parents=True)
            p.write_text(skill("dev-plug", "From a plugin."))
        p = self.home / ".claude/skills/dev-mine/SKILL.md"
        p.parent.mkdir(parents=True)
        p.write_text(skill("dev-mine", "Mine."))
        self.assertEqual(self.run_commands("list"), 0)
        self.assertEqual(self.group("Core"), ["/dev-help — Lists every dev- command."])
        self.assertEqual(self.group("Used by agents"), ["/dev-run-ci-locally — Runs the checks."])
        self.assertEqual(self.group("This repository"), [
            "/dev-old — An old command.  (.claude/commands)",
            "/dev-repo-thing — Repository thing.  (.agents/skills)",
        ])
        self.assertEqual(self.group("Plugins"), ["/dev-plug — From a plugin.  (plugin tools)"])
        self.assertEqual(self.group("This Mac"), ["/dev-mine — Mine.  (~/.claude/skills)"])
        self.assertEqual(self.lines[-4], "Releases, plugins, sync and new repositories: `/dev-help` in pa-agent-kit")
        self.assertEqual(self.lines[-3], "done: listed 6 command(s); nothing waits for PA")
        self.assertTrue(self.lines[-1].startswith("next: "))

    def test_missing_places_print_one_line(self):
        self.assertEqual(self.run_commands("list"), 0)
        self.assertEqual(self.group("Plugins"), ["none on this machine"])
        self.assertEqual(self.group("This Mac"), ["none on this machine"])
        self.assertEqual(self.group("This repository"), ["none"])

    def test_a_folded_description_is_joined(self):
        self.write(".agents/skills/dev-long/SKILL.md", "---\nname: dev-long\ndescription: >-\n  First part\n  second part.\n---\n")
        self.run_commands("list")
        self.assertIn("/dev-long — First part second part.  (.agents/skills)", self.group("This repository"))

    def test_the_workshop_has_no_pointer_line(self):
        result = subprocess.run([str(HARNESS / "commands"), "list"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("in pa-agent-kit", result.stdout)

    # --- list --check

    def test_check_passes_on_good_skills_and_one_file_through_two_links(self):
        self.write(".agents/skills/dev-repo-thing/SKILL.md", skill("dev-repo-thing"))
        (self.repo / ".claude").mkdir()
        os.symlink("../.agents/skills", self.repo / ".claude/skills")  # the workshop's directory link
        self.assertEqual(self.run_commands("list", "--check"), 0, self.out)
        self.assertEqual(self.lines[-3], "done: list --check passed: 3 command(s), no problem")

    def test_check_fails_on_each_problem(self):
        self.write(".agents/skills/dev-nodesc/SKILL.md", "---\nname: dev-nodesc\n---\n")
        self.write(".agents/skills/dev-wrong/SKILL.md", skill("dev-other"))
        self.write(".agents/skills/dev-help/SKILL.md", skill("dev-help", "A second dev-help."))
        self.assertEqual(self.run_commands("list", "--check"), 1)
        self.assertIn("commands: dev-nodesc (.agents/skills) has no description", self.out)
        self.assertIn("commands: dev-wrong (.agents/skills): name dev-other differs from its directory", self.out)
        self.assertIn("commands: dev-help is defined twice: .harness/skills and .agents/skills", self.out)
        self.assertTrue(self.lines[-1].startswith("next: fix each line above"))

    def test_a_core_skill_without_the_prefix_fails_the_check(self):
        self.write(".harness/skills/helper/SKILL.md", skill("helper"))
        self.assertEqual(self.run_commands("list", "--check"), 1)
        self.assertIn("core skill helper does not start with dev-", self.out)

    # --- next

    def test_next_offline_items(self):
        self.git("config", "--unset", "core.hooksPath")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("commit", "-q", "--allow-empty", "-m", "ahead on origin")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.assertEqual(self.run_commands("next", GH_LOGGED_IN="1"), 0)
        self.assertEqual(self.lines[1:4], [
            "  - the core's git hooks are not installed in this clone: ./dev setup",
            "  - local main is 1 commit(s) behind origin/main (as of the last fetch): /dev-update-local-repo",
            "  - gh is logged in with your own account, which agents must never use: gh auth logout",
        ])
        self.assertEqual(self.lines[-3:], [
            "done: 3 item(s) wait for PA",
            "left for PA: the 3 item(s) under 'Waiting for you'",
            "next: ./dev setup",
        ])

    def test_next_with_nothing_waiting(self):
        self.assertEqual(self.run_commands("next"), 0)
        self.assertEqual(self.lines, ["Waiting for you", "  nothing", "done: nothing waits for PA",
                                      "left for PA: nothing", "next: /dev-help"])

    def test_online_without_a_token_says_so(self):
        self.assertEqual(self.run_commands("next", "--online"), 1)
        self.assertIn("online checks skipped: no bot token in GH_TOKEN: /dev-status", self.out)

    def test_partial_status_keeps_verified_pull_requests(self):
        (self.work / "open_prs").write_text("7\ttrue\tReview me\thttps://example.invalid/7\n")
        (self.work / "releases").unlink()
        self.assertEqual(self.run_commands("next", "--online", GH_TOKEN="fixture"), 1)
        self.assertIn("PR #7", self.out)
        self.assertIn("draft-releases", self.out)
        self.assertNotIn("nothing waits", self.out)

    def test_online_items(self):
        (self.work / "open_prs").write_text("7\ttrue\tWork in progress\thttps://github.com/example/demo/pull/7\n"
                                            "8\tfalse\tDone work\thttps://github.com/example/demo/pull/8\n")
        (self.work / "releases").write_text("tool/v1.2.0\n")
        self.git("branch", "feat/merged")
        tip = self.git("rev-parse", "feat/merged")
        (self.work / "merged").write_text(f"feat/merged 5 {tip}\n")
        self.git("branch", "feat/open")
        self.git("tag", "harness-v1.0")
        self.git("tag", "harness-v1.10")
        self.git("tag", "harness-v1.9")
        self.git("push", "-q", str(self.workshop), "--tags")
        self.assertEqual(self.run_commands("next", "--online", GH_TOKEN="x"), 0, self.err)
        self.assertEqual(self.lines[1:6], [
            '  - PR #7 "Work in progress" is a draft: mark it ready on GitHub once its work is done: https://github.com/example/demo/pull/7',
            '  - PR #8 "Done work" is ready: review and merge it on GitHub: https://github.com/example/demo/pull/8',
            "  - local branches merged on GitHub: feat/merged: /dev-delete-merged-branches feat/merged",
            "  - draft release tool/v1.2.0 waits to be published: /dev-run-with-owner-token",
            "  - core harness-v1.10 is out; this repository has harness-v1.0: /dev-harness-sync harness-v1.10",
        ])
        self.assertTrue(self.git("rev-parse", "--verify", "feat/merged"))  # a dry run deleted nothing

    def test_usage_errors(self):
        for args in ((), ("bogus",), ("next", "--check"), ("list", "--check", "--online")):
            with self.subTest(args=args):
                self.assertEqual(self.run_commands(*args), 2)
                self.assertIn("done: refused; nothing changed", self.err)


if __name__ == "__main__":
    unittest.main()
