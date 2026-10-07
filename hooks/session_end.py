#!/usr/bin/env python3
"""Save a summary of an agent session per git branch, when the session ends.

Called by the Claude Code SessionEnd hook (JSON on stdin) and by the pi / omp extension
(`--payload '<json>'`). Payload: {session_id, transcript_path, cwd, reason, agent?}.

Writes <git-common-dir>/atlas/sessions/<session_id>.json so branch reports still find the
session after transcripts are cleaned up. With ATLAS_GIT_NOTES=1 it also appends the summary
to refs/notes/atlas-sessions on HEAD; teammates get it once notes are pushed
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


def read_payload(argv):
    if "--payload" in argv:
        return json.loads(argv[argv.index("--payload") + 1])
    return json.load(sys.stdin)


def main(argv):
    data = read_payload(argv)
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
        by_branch = sessions.summarize_transcript(transcript, agent=data.get("agent"))
        by_branch = {b: s for b, s in by_branch.items() if s.get("tool_calls") or s.get("task")}
        if not by_branch:
            return
        session_id = data.get("session_id") or next(iter(by_branch.values()))["id"]
        record = {
            "session_id": session_id,
            "agent": data.get("agent") or next(iter(by_branch.values())).get("agent"),
            "ended_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
            "end_reason": data.get("reason"),
            "head": git(cwd, "rev-parse", "HEAD"),
            "by_branch": by_branch,
        }
        folder = os.path.join(common, "atlas", "sessions")
        os.makedirs(folder, exist_ok=True)
        safe_id = "".join(c if c.isalnum() or c in "-_." else "_" for c in session_id)
        tmp = os.path.join(folder, safe_id + ".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False)
        os.replace(tmp, os.path.join(folder, safe_id + ".json"))
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
        main(sys.argv[1:])
    except Exception:
        pass
    sys.exit(0)
