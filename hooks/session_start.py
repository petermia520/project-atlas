#!/usr/bin/env python3
"""Claude Code SessionStart hook: in repos that use Project Atlas, tell the agent its session id
and the commit-trailer convention, so branch reports can link commits to sessions and decisions.
(pi and omp get the same text from extensions/project-atlas.ts.)

Active only when the repo has .project-map/atlas.json (or ATLAS_TRAILERS=1). Never fails the session.
"""

import json
import os
import subprocess
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PLUGIN_ROOT, "scripts"))


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    cwd = data.get("cwd") or os.getcwd()
    proc = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if proc.returncode != 0:
        return
    root = proc.stdout.strip()
    if not (os.path.isfile(os.path.join(root, ".project-map", "atlas.json")) or os.environ.get("ATLAS_TRAILERS") == "1"):
        return
    from atlas import agents  # noqa: E402
    context = agents.trailer_context(data.get("session_id"), os.path.join(PLUGIN_ROOT, "scripts", "atlas_cli.py"))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # a hook must never break the session
        pass
    sys.exit(0)
