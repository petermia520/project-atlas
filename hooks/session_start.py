#!/usr/bin/env python3
"""SessionStart hook: in repos that use Project Atlas, tell the agent its session id and the
commit-trailer convention, so branch reports can link commits to sessions and decisions.

Active only when the repo has .project-map/atlas.json (or ATLAS_TRAILERS=1). Never fails the session.
"""

import json
import os
import subprocess
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    cwd = data.get("cwd") or os.getcwd()
    session_id = data.get("session_id") or "unknown"
    proc = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if proc.returncode != 0:
        return
    root = proc.stdout.strip()
    if not (os.path.isfile(os.path.join(root, ".project-map", "atlas.json")) or os.environ.get("ATLAS_TRAILERS") == "1"):
        return
    cli = os.path.join(PLUGIN_ROOT, "scripts", "atlas_cli.py")
    context = (
        "This repository uses Project Atlas for branch reviews. When you create a git commit in this session, "
        "end the commit message with these trailers (after a blank line, before any Co-Authored-By line):\n"
        "Agent-Session: %s\n"
        "Agent-Decision: <one line per non-obvious choice and why, e.g. 'used X instead of Y because Z'> (optional, repeatable)\n"
        "Agent-Assumption: <one line per assumption the task did not settle> (optional, repeatable)\n"
        "Reviewers read these to understand the branch. Do not add trailers to commits you did not write.\n"
        "Project Atlas CLI: python3 \"%s\"" % (session_id, cli)
    )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # a hook must never break the session
        pass
    sys.exit(0)
