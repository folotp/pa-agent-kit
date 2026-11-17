"""Tests of the guard (harness/guard) and of its bindings.

The guard runs as a subprocess with each agent's payload shape: Claude Code and Codex
(`tool_name`, `tool_input.command`, `permission_mode`; deny = exit 2) and Antigravity
(`toolCall.name`, `toolCall.args.CommandLine`; deny = a JSON decision on stdout, exit 0).
It needs jq on the system PATH, as in a real hook.
"""

import json
import os
import subprocess
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


class BindingTest(unittest.TestCase):
    """The repository's own bindings are the templates, with the core in harness/ not .harness/."""

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
