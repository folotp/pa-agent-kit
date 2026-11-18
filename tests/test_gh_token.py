"""Tests of the token script (harness/gh-token.sh) that need no Keychain item and no network.

The script is sourced in bash (it runs `main` only when executed), so each test calls one function
or runs the script with arguments that stop before any key is read. Minting a real token is PA's
read-back (`gh-token.sh claude --read-only --info`), not a unit test. Needs `jq` on the system PATH.
"""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "harness" / "gh-token.sh"
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"


def bash(script, **env):
    return subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}"\n{script}'],
        env={"HOME": os.environ["HOME"], "PATH": SYSTEM_PATH, **env},
        capture_output=True, text=True, timeout=30,
    )


@unittest.skipUnless(shutil.which("jq", path=SYSTEM_PATH), "jq not on the system PATH")
class TokenRequestTest(unittest.TestCase):
    INSTALLATION = json.dumps({"id": 1, "permissions": {"contents": "write", "pull_requests": "write", "metadata": "read"}})

    def request(self, read_only):
        result = bash(f"token_request repo '{self.INSTALLATION}' '{read_only}'")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_default_request_is_limited_to_the_repository(self):
        self.assertEqual(self.request(""), {"repositories": ["repo"]})

    def test_read_only_request_narrows_every_permission_to_read(self):
        self.assertEqual(
            self.request("1"),
            {"repositories": ["repo"], "permissions": {"contents": "read", "pull_requests": "read", "metadata": "read"}},
        )


class ArgumentsTest(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run(
            [str(SCRIPT), *args], env={"HOME": os.environ["HOME"], "PATH": SYSTEM_PATH},
            capture_output=True, text=True, timeout=30,
        )

    def test_unknown_option_prints_usage(self):
        result = self.run_script("claude", "--frobnicate")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--read-only", result.stderr)

    def test_no_command_after_separator_is_refused(self):
        result = self.run_script("claude", "--read-only", "--")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no command after --", result.stderr)


if __name__ == "__main__":
    unittest.main()
