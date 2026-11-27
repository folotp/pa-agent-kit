"""Tests of the guard (harness/guard) and of its bindings.

The guard runs as a subprocess with each agent's payload shape: Claude Code and Codex
(`tool_name`, `tool_input.command`, `permission_mode`; deny = exit 2) and Antigravity
(`toolCall.name`, `toolCall.args.CommandLine`; deny = a JSON decision on stdout, exit 0).
It needs jq on the system PATH, as in a real hook.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "harness" / "guard"
SYSTEM_PATH = "/usr/bin:/bin"

ALWAYS_DENIED = [
    "git push origin main",
    "git push origin HEAD:main",
    "git push origin HEAD:refs/heads/main",
    "git -C /tmp/x push origin master",
    "cd /tmp && git push origin main",
    "git push --force origin feat",
    "git push -f origin feat",
    "git push --force-with-lease=feat origin feat",
    "git push origin +feat",
    "git push --delete origin feat",
    "git push origin :feat",
    "git commit --no-verify -m wip",
    "git push --no-verify origin HEAD:refs/heads/feat",
    "gh pr merge 83 --squash",
    "gh pr ready 83",
    "gh api -X PUT repos/o/r/pulls/83/merge",
    "ls; gh pr merge 83",
    # Session 24 (K3): quoting, escapes and continued lines are removed before matching.
    '"git" push origin main',
    "\\git push origin main",
    'git push origin "main"',
    "git push origin 'main'",
    'git push origin HEAD:"main"',
    "git push origin $'main'",
    'git push origin HEAD:ma""in',
    "git push origin \\\nmain",
    "git push \\\n  --force origin feat",
    # K3: every branch, wildcard and matching refspecs, combined and abbreviated flags.
    "git push origin --all",
    "git push origin 'refs/heads/*:refs/heads/*'",
    "git push origin :",
    "git push -fu origin feat",
    "git push -uf origin feat",
    "git push --forc origin feat",
    "git push --del origin feat",
    # K3: hooks skipped and verbs hidden on the command line.
    "git commit -n -m wip",
    "git commit -anm wip",
    "git -c core.hooksPath=/dev/null commit -m wip",
    "git -c core.hookspath=/dev/null commit -m wip",
    "git --config-env=core.hooksPath=EMPTY commit -m wip",
    "git -c alias.p=push p origin main",
    "git -c alias.c=commit c -m wip",
    # K2: flags before the verb, and the GraphQL mutations anywhere.
    "gh pr -R folotp/pa-agent-kit merge 5",
    "gh pr --repo folotp/pa-agent-kit ready 5",
    "gh pr -R folotp/pa-agent-kit merge --help",
    "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"X\"}) { clientMutationId } }'",
    "gh api graphql -f query='mutation { markPullRequestReadyForReview(input: {pullRequestId: \"X\"}) { clientMutationId } }'",
    "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {pullRequestId: \"X\"}) { clientMutationId } }'",
    # K8: releases stay drafts.
    "gh release create plugin/v1.0.0",
    "gh release create plugin/v1.0.0 --notes x",
    "gh release create plugin/v1.0.0 --draft=false",
    "gh release -R o/r new plugin/v1.0.0",
    "gh release edit plugin/v1.0.0 --draft=false",
    "gh release edit plugin/v1.0.0 --draft=0",
    "gh api -X POST repos/o/r/releases -f tag_name=v1",
    "gh api repos/o/r/releases -f tag_name=v1",
    "gh api --method PATCH repos/o/r/releases/5 -F draft=false",
    # Codex second read of 24b (C4): inherited flags before the command group.
    "gh -R owner/repo pr merge 5 --squash",
    "gh --repo owner/repo pr ready 5",
    "gh -R owner/repo release create v1 --notes x",
    "gh -R owner/repo release edit v1 --draft=false",
    "gh -R owner/repo api -X PUT repos/o/r/pulls/5/merge",
    # C5: a quoted separator must not cut a command in two; quoted text is not an option.
    "git -C '/tmp/a;b' push origin HEAD:main",
    'git -C "/tmp/a|b" push --force origin feat',
    "gh release create v1 --notes 'Use --draft for previews'",
    'gh release create v1 --notes "x -d y"',
    "gh release create v1 --title $'a --draft b'",
]

ALWAYS_ALLOWED = [
    "git status",
    "git push origin HEAD:refs/heads/kit-core-guard",
    "git push origin feat-main",
    "git log --oneline main",
    "gh pr create --draft --base main --head feat",
    "gh pr view 83",
    "./dev gate",
    "./dev ci",
    "grep -n deploy docs/x.md",
    # Near misses of the session 24 patterns (K2, K3, K8).
    "git push origin HEAD:mainline",
    "git push origin feature/main-fix",
    "git push origin 'HEAD:refs/heads/feat'",
    "git push --follow-tags origin HEAD:refs/heads/feat",
    "git push -o ci.skip origin HEAD:refs/heads/feat",
    "git push -u origin HEAD:refs/heads/feat",
    "git log --grep main",
    "git commit -m 'fix n'",
    "git commit -sm wip",
    "git commit --amend --no-edit",
    "git -C /tmp/x status",
    "git config --get core.hooksPath",
    "gh pr view 5",
    "gh pr create --title 'ready to merge' --body x",
    "gh pr -R folotp/pa-agent-kit view 5",
    "gh release create v1 --draft",
    "gh release create plugin/v1.0.0 -d --notes x",
    "gh release create plugin/v1.0.0 --draft=true",
    "gh release view plugin/v1.0.0",
    "gh release upload plugin/v1.0.0 x.zip",
    "gh api repos/o/r/releases",
    "gh api -X POST repos/o/r/releases -F draft=true -f tag_name=v1",
    # Near misses of the Codex C4 and C5 fixes.
    "gh -R owner/repo pr view 5",
    "gh --repo owner/repo release view v1",
    "gh -R owner/repo release create v1 --draft --notes 'a; b'",
    "bash -c 'gh release create v1 --draft'",
    "git commit -m 'fix; see -n'",
    "git -C '/tmp/a;b' push origin HEAD:refs/heads/feat",
]

RELEASES = [
    "./dev deploy --domain light",
    "./dev apply",
    '"./dev" deploy --check',
    "'./dev' 'apply'",
    "/x/repo/.harness/dev deploy --check",
    "mise exec -- ./dev deploy --restart",
    "harness/gh-token.sh claude -- ./dev deploy --check",
    "bash -c './dev apply'",
    "harness/gate release deploy",
    ".harness/gate --stage2 deploy",
]


def run_guard(agent, payload, env=None, path=SYSTEM_PATH):
    full_env = {"PATH": path}
    full_env.update(env or {})
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        ["/bin/bash", str(GUARD), agent], input=data, env=full_env, capture_output=True, text=True, timeout=30
    )


def claude(command, mode="default", tool="Bash"):
    return {"tool_name": tool, "tool_input": {"command": command}, "permission_mode": mode, "cwd": "/x"}


def antigravity(command, tool="run_command"):
    return {"toolCall": {"name": tool, "args": {"CommandLine": command, "Cwd": "/x"}}, "conversationId": "c"}


class GuardTest(unittest.TestCase):
    def assertDenied(self, result, message="", agent="claude"):
        if agent == "antigravity":
            self.assertEqual(result.returncode, 0, result.stderr)
            decision = json.loads(result.stdout)
            self.assertEqual(decision["decision"], "deny")
            self.assertIn(message, decision["reason"])
        else:
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(message, result.stderr)

    def assertAllowed(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_always_denied_in_every_agent_and_mode(self):
        for command in ALWAYS_DENIED:
            with self.subTest(command):
                self.assertDenied(run_guard("claude", claude(command)))
                self.assertDenied(run_guard("codex", claude(command, "bypassPermissions")))
                self.assertDenied(run_guard("antigravity", antigravity(command)), agent="antigravity")

    def test_ordinary_commands_pass_everywhere(self):
        for command in ALWAYS_ALLOWED:
            with self.subTest(command):
                self.assertAllowed(run_guard("claude", claude(command, "bypassPermissions")))
                self.assertAllowed(run_guard("codex", claude(command)))
                self.assertAllowed(run_guard("antigravity", antigravity(command)))

    def test_release_passes_where_a_prompt_is_answered(self):
        for mode in ("default", "acceptEdits", "plan", "auto"):
            for command in RELEASES:
                with self.subTest(mode=mode, command=command):
                    self.assertAllowed(run_guard("claude", claude(command, mode)))

    def test_release_is_denied_where_nobody_answers(self):
        for command in RELEASES:
            with self.subTest(command):
                self.assertDenied(run_guard("claude", claude(command, "bypassPermissions")), "permission mode 'bypassPermissions'")
                self.assertDenied(run_guard("codex", claude(command, "dontAsk")), "permission mode 'dontAsk'")
                self.assertDenied(run_guard("claude", claude(command, "")), "permission mode 'not given'")
                self.assertDenied(run_guard("claude", claude(command), {"CLAUDE_CODE_REMOTE": "true"}), "a cloud session")
                self.assertDenied(run_guard("antigravity", antigravity(command)), "release verbs", "antigravity")

    def test_other_tools_are_not_judged(self):
        self.assertAllowed(run_guard("claude", claude("git push origin main", tool="Read")))
        self.assertAllowed(run_guard("codex", claude("*** push origin main", "bypassPermissions", tool="apply_patch")))
        self.assertAllowed(run_guard("antigravity", antigravity("git push origin main", tool="view_file")))

    def test_long_commands_are_judged_well_within_the_hook_timeout(self):
        # Codex second read of 24b: the bindings give the hook 10 s and a timed-out hook lets the
        # call through. Before the jq views, 6 KB took 8 s (bash 3.2 ${var//…} is quadratic).
        message = "lorem ipsum dolor; sit 'amet' " * 6000  # about 180 KB
        for command, denied in (
            (f'git commit -m "{message}"', False),
            (f'git commit -m "{message}"; git push origin main', True),
            ("git commit -m " + "lorem ipsum dolor sit amet " * 7000, False),
        ):
            with self.subTest(length=len(command), denied=denied):
                start = time.monotonic()
                result = run_guard("claude", claude(command))
                self.assertLess(time.monotonic() - start, 5)
                if denied:
                    self.assertDenied(result, "pushes to main")
                else:
                    self.assertAllowed(result)

    def test_a_command_too_long_to_judge_in_time_denies(self):
        self.assertDenied(run_guard("claude", claude("ls " + "x" * 200_000)), "too long")
        self.assertDenied(run_guard("antigravity", antigravity("ls " + "x" * 200_000)), "too long", "antigravity")

    def test_fails_closed(self):
        self.assertDenied(run_guard("claude", claude("git status"), path="/nonexistent"), "jq is missing")
        self.assertDenied(
            run_guard("antigravity", antigravity("git status"), path="/nonexistent"), "jq is missing", "antigravity"
        )
        self.assertDenied(run_guard("claude", "not json"), "cannot read the hook payload")
        self.assertDenied(run_guard("claude", {"tool_input": {"command": "ls"}}), "cannot read the hook payload")
        self.assertDenied(run_guard("antigravity", {"tool_name": "Bash"}), "cannot read the hook payload", "antigravity")
        self.assertDenied(run_guard("gemini", claude("git status")), "unknown agent")
        self.assertDenied(run_guard("", claude("git status")), "unknown agent")
        # Session 24b: the split used a here-document, which needs a writable temporary folder;
        # without one every command passed.
        self.assertDenied(run_guard("claude", claude("ls; git push origin main"), {"TMPDIR": "/nonexistent"}))

    def test_a_judged_command_that_is_not_a_string_denies(self):
        # Session 24 (K3): an array or a number used to read as empty and pass.
        for value in (["git", "push", "origin", "main"], 5, {"argv": ["ls"]}, True):
            with self.subTest(value=value):
                self.assertDenied(run_guard("claude", claude(value)), "not a string")
                self.assertDenied(run_guard("codex", claude(value, "bypassPermissions")), "not a string")
                self.assertDenied(run_guard("antigravity", antigravity(value)), "not a string", "antigravity")
        # A tool that is not judged keeps passing whatever it carries; a missing command passes.
        self.assertAllowed(run_guard("claude", claude(["git", "push", "origin", "main"], tool="Read")))
        self.assertAllowed(run_guard("claude", {"tool_name": "Bash", "tool_input": {}, "permission_mode": "default"}))
        self.assertAllowed(run_guard("claude", claude(None)))

    # 24g I2 (24f F2): a local branch deleted by force, with nothing checking that it was merged.
    BRANCH_FORCE_DELETES = [
        "git branch -D feat/x",
        "git branch -vD feat/x",
        "git -C /tmp/r branch -D feat/x",
        "cd /tmp && git branch -D feat/x",
        "git branch -d -f feat/x",
        "git branch -f -d feat/x",
        "git branch -df feat/x",
        "git branch -fd feat/x",
        "git branch --delete --force feat/x",
        "git branch --force --delete feat/x",
        "git branch --delete -f feat/x",
        "git branch -d --force feat/x",
        "git branch --del --forc feat/x",
        "'git' branch '-D' feat/x",
        "git branch \\\n  -D feat/x",
        "bash -c 'git branch -D feat/x'",
    ]
    BRANCH_PASSES = [
        "git branch -d feat/x",
        "git branch --delete feat/x",
        "git branch --list",
        "git branch --show-current",
        "git branch -m old new",
        "git branch -M old new",
        "git branch -c a b",
        "git branch -f feat origin/main",
        "git branch -u origin/feat-d feat",
        "git branch --format=%(refname:short) --list 'feat/*'",
        "harness/gh-token.sh claude -- harness/git-prune-merged.sh feat/x",
        ".harness/gh-token.sh claude -- .harness/git-prune-merged.sh feat/x",
        ".harness/gh-token.sh claude -- .harness/git-prune-merged.sh --all",
        ".harness/gh-token.sh codex -- .harness/git-prune-merged.sh --dry-run feat/x",
        "git log --oneline -D",
    ]

    def test_a_forced_branch_deletion_is_denied_with_the_prune_command(self):
        for command in self.BRANCH_FORCE_DELETES:
            with self.subTest(command):
                self.assertDenied(run_guard("claude", claude(command)), "/dev-delete-merged-branches")
                self.assertDenied(run_guard("codex", claude(command, "bypassPermissions")), "/dev-delete-merged-branches")
                self.assertDenied(run_guard("antigravity", antigravity(command)), "/dev-delete-merged-branches", "antigravity")

    def test_branch_commands_that_do_not_force_a_deletion_pass(self):
        for command in self.BRANCH_PASSES:
            with self.subTest(command):
                self.assertAllowed(run_guard("claude", claude(command)))
                self.assertAllowed(run_guard("antigravity", antigravity(command)))

    def test_the_push_refusal_names_the_token_script_where_it_is(self):
        """The workshop's guard names harness/gh-token.sh, a consumer's .harness/gh-token.sh."""
        self.assertDenied(run_guard("claude", claude("git push origin main")), "`harness/gh-token.sh <bot> -- git push origin HEAD:refs/heads/<branch>`")
        with tempfile.TemporaryDirectory() as root:
            copy = Path(root) / ".harness" / "guard"
            copy.parent.mkdir()
            shutil.copy2(GUARD, copy)
            result = subprocess.run([str(copy), "claude"], input=json.dumps(claude("git push origin main")),
                                    capture_output=True, text=True, env={"PATH": SYSTEM_PATH}, timeout=30)
        self.assertDenied(result, "`.harness/gh-token.sh <bot> --")


class BindingTest(unittest.TestCase):
    """The repository's own bindings are the templates, with the core in harness/ not .harness/."""

    def test_codex_release_handoff_decisions(self):
        # Run only the binding command. The proposed agent action is JSON on its stdin.
        config = json.loads((ROOT / ".codex/hooks.json").read_text())
        hook = config["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        api = next(command for command in ALWAYS_DENIED if command.startswith("gh api --method PATCH"))
        publish = "harness/gh-token.sh owner -- " + api
        source = f"""cat > planner.py <<'PYCODE'
print("{publish}")
PYCODE"""
        harmless = "cat <<'TEXT' > readme.txt\nhello\nTEXT"
        for label, command, expected in (
            ("source", source, 0),
            ("two writes", harmless + "\n" + source, 0),
            ("publish", publish, 2),
            ("write then publish", harmless + "\n" + publish, 2),
            ("publish then write", publish + "\n" + harmless, 2),
            ("source then publish", source + "\n" + publish, 2),
            ("unterminated", source.removesuffix("\nPYCODE"), 2),
            ("unquoted delimiter", source.replace("'PYCODE'", "PYCODE"), 2),
            ("interpreter", source.replace("cat >", "sh >"), 2),
            ("pipeline", source.replace("<<'PYCODE'", "<<'PYCODE' | sh"), 2),
        ):
            with self.subTest(label):
                payload = claude(command, tool="exec_command")
                result = subprocess.run(
                    ["/bin/sh", "-c", hook], input=json.dumps(payload), cwd=ROOT,
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, expected, result.stderr)
                if expected:
                    self.assertIn("releases stay drafts", result.stderr)

    def test_bindings_match_the_templates(self):
        for path in (".claude/settings.json", ".codex/hooks.json", ".agents/hooks.json"):
            with self.subTest(path):
                template = (ROOT / "harness" / "bindings" / path).read_text().replace("/.harness/", "/harness/")
                expected = json.loads(template)
                actual = json.loads((ROOT / path).read_text())
                if path == ".agents/hooks.json":
                    self.assertEqual(actual["harness-guard"], expected["harness-guard"])
                else:
                    self.assertIn(expected["hooks"]["PreToolUse"][0], actual["hooks"]["PreToolUse"])

    def test_templates_call_the_guard_with_their_agent(self):
        for path, agent, matcher in (
            (".claude/settings.json", "claude", "Bash"),
            (".codex/hooks.json", "codex", "Bash"),
            (".agents/hooks.json", "antigravity", "run_command"),
        ):
            with self.subTest(path):
                data = json.loads((ROOT / "harness" / "bindings" / path).read_text())
                entry = (data["hooks"] if "hooks" in data else data["harness-guard"])["PreToolUse"][0]
                self.assertEqual(entry["matcher"], matcher)
                self.assertTrue(entry["hooks"][0]["command"].endswith(f'/.harness/guard" {agent}'))


if __name__ == "__main__":
    unittest.main()
