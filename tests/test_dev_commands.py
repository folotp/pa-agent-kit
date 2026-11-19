"""Cross-check the discoverable commands, the sealed core and the guard's instructions."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import test_guard
from test_guard import ALWAYS_DENIED, RELEASES, claude, run_guard

CORE = Path(__file__).resolve().parents[1] / "harness"


class DevCommandsTest(unittest.TestCase):
    def test_index_lists_each_shipped_skill_and_its_dependencies_exist(self):
        manifest = (CORE / "core.files").read_text().splitlines()
        self.assertIn("skills/", manifest)
        with tempfile.TemporaryDirectory() as home:
            env = {**os.environ, "HOME": home, "GH_CONFIG_DIR": home}
            for args in (["list", "--check"], ["list"]):
                listing = subprocess.check_output([CORE / "commands", *args], cwd=CORE.parent,
                                                  env=env, text=True)
        for skill in (CORE / "skills").iterdir():
            with self.subTest(skill=skill.name):
                self.assertTrue(skill.name.startswith("dev-"))
                _, metadata, body = (skill / "SKILL.md").read_text().split("---", 2)
                self.assertIn(f"name: {skill.name}", metadata.splitlines())
                self.assertRegex(metadata, r"(?m)^description: \S")
                self.assertEqual(len(re.findall(r"(?m)^\s+/" + re.escape(skill.name) + r"\s", listing)), 1)
                references = set(re.findall(r"(?:<core>|\.harness)/([\w.-]+)", body))
                if "./dev " in body:
                    references.add("dev")
                self.assertTrue(references)
                for path in references:
                    self.assertIn(path, manifest)
                    self.assertTrue((CORE / path).is_file())

    def test_user_facing_scripts_end_with_the_next_step(self):
        # Refusals exercise the public entry points without a token, a push or a release.
        for script, args in {
            "dev": ["check", "extra"], "gate": ["unknown"], "gh-token.sh": ["owner"],
            "git-prune-merged.sh": ["--help"], "commands": ["unknown"], "harness-sync": ["--help"],
        }.items():
            with self.subTest(script=script):
                run = subprocess.run([CORE / script, *args], cwd=CORE.parent, text=True,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                self.assertNotEqual(run.returncode, 0)
                self.assertEqual([line.split(": ", 1)[0] for line in run.stdout.strip().splitlines()[-3:]],
                                 ["done", "left for PA", "next"])

    def test_every_denial_names_the_sanctioned_way(self):
        """24i's refusal rule: each reason names a /dev- command or a `command` to run."""
        sanctioned = re.compile(r"/dev-[a-z]+(-[a-z]+)*|`[^`]+`")
        results = [run_guard("claude", claude(c)) for c in ALWAYS_DENIED + test_guard.GuardTest.BRANCH_FORCE_DELETES]
        results += [run_guard("claude", claude(c, "dontAsk")) for c in RELEASES]
        results += [
            run_guard("claude", claude("git status"), path="/nonexistent"),
            run_guard("claude", "not json"),
            run_guard("gemini", claude("git status")),
            run_guard("claude", claude(["ls"])),
            run_guard("claude", claude("ls " + "x" * 200_000)),
        ]
        for result in results:
            with self.subTest(result.stderr):
                self.assertEqual(result.returncode, 2)
                self.assertRegex(result.stderr, sanctioned)
                # Session 25c supplies the workshop-only release command.
                for name in re.findall(r"/(dev-[a-z-]+)", result.stderr):
                    self.assertTrue((CORE / "skills" / name / "SKILL.md").is_file()
                                    or name == "dev-plugin-release", name)

