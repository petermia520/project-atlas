#!/usr/bin/env python3
"""SessionEnd hook: save a summary of the session per git branch.

Writes <git-common-dir>/atlas/sessions/<session_id>.json so branch reports still find the
session after Claude Code cleans up old transcripts. With ATLAS_GIT_NOTES=1 it also appends
the summary to refs/notes/atlas-sessions on HEAD, which teammates receive once notes are pushed
(`git push origin refs/notes/atlas-sessions`).

Never fails the session; errors go to <git-common-dir>/atlas/hook-errors.log.
"""

import datetime
import json
import os
import subprocess
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))


def git(cwd, *args):
    proc = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def main():
    data = json.load(sys.stdin)
    transcript = data.get("transcript_path")
    cwd = data.get("cwd") or os.getcwd()
    if not transcript or not os.path.isfile(transcript):
        return
    common = git(cwd, "rev-parse", "--git-common-dir")
    if not common:
        return
    common = common if os.path.isabs(common) else os.path.normpath(os.path.join(cwd, common))
    from atlas import sessions  # noqa: E402

    try:
        by_branch = sessions.summarize_transcript(transcript)
        by_branch = {b: s for b, s in by_branch.items() if s.get("tool_calls") or s.get("task")}
        if not by_branch:
            return
        session_id = data.get("session_id") or next(iter(by_branch.values()))["id"]
        record = {
            "session_id": session_id,
            "ended_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
            "end_reason": data.get("reason"),
            "head": git(cwd, "rev-parse", "HEAD"),
            "by_branch": by_branch,
        }
        folder = os.path.join(common, "atlas", "sessions")
        os.makedirs(folder, exist_ok=True)
        tmp = os.path.join(folder, session_id + ".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False)
        os.replace(tmp, os.path.join(folder, session_id + ".json"))
        if os.environ.get("ATLAS_GIT_NOTES") == "1" and record["head"]:
            slim = dict(record, by_branch={b: {k: v for k, v in s.items() if k != "transcript_path"} for b, s in by_branch.items()})
            subprocess.run(["git", "-C", cwd, "notes", "--ref=atlas-sessions", "append", "-m",
                            json.dumps(slim, ensure_ascii=False, separators=(",", ":")), record["head"]],
                           capture_output=True)
    except Exception:
        os.makedirs(os.path.join(common, "atlas"), exist_ok=True)
        with open(os.path.join(common, "atlas", "hook-errors.log"), "a", encoding="utf-8") as fh:
            fh.write("%s session_end %s\n%s\n" % (datetime.datetime.now().isoformat(), transcript, traceback.format_exc()))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
