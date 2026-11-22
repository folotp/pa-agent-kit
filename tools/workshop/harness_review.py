#!/usr/bin/env python3
"""Collect workshop harness review evidence and print the next step."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / "docs/workaround-register.md"
PROBE = re.compile(r"(?m)^- \*\*Probe:\*\* \x60(tools/probes/[\w.-]+\.sh)\x60")


def report(command):
    print("$ " + " ".join(map(str, command)), flush=True)
    try:
        return subprocess.run(command, cwd=ROOT, timeout=180).returncode
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"inconclusive: {error}")
        return 2


def ending(done, left, next_command):
    print(f"done: {done}\nleft for PA: {left}\nnext: {next_command}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="list probes without running them")
    args = parser.parse_args()
    if not (ROOT / "harness/core.files").is_file() or not REGISTER.is_file():
        ending("workshop harness review could not start", "open the workshop checkout", "/dev-harness-review")
        return 1
    probes = PROBE.findall(REGISTER.read_text())
    if args.dry_run:
        for probe in probes:
            print(probe)
        ending(f"found {len(probes)} workshop probes", "choose when to run the review", "/dev-harness-review")
        return 0
    if report(["./dev", "check"]):
        ending("workshop check failed", "review the diagnostic above", "/dev-run-ci-locally")
        return 1
    for tool in ("python", "shellcheck", "actionlint"):
        if shutil.which("mise"):
            report(["mise", "latest", tool])
    for client in ("claude", "codex", "gemini", "agy"):
        if shutil.which(client):
            report([client, "--version"])
        else:
            print(f"inconclusive: {client} is unavailable")
    report(["./dev", "specs", "check"])
    for probe in probes:
        result = report([str(ROOT / probe)])
        if result == 10:
            result = 10 if report([str(ROOT / probe)]) == 10 else 2
        print(f"{probe}: " + {0: "still needed", 10: "propose removal"}.get(result, "inconclusive"))
    ending("collected workshop review evidence", "decide which proposals should become PRs", "review the numbered proposals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
