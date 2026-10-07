---
name: branch-report
description: Write a review report for a branch or pull request, especially one an AI agent wrote — what changed, what it affects across the project map, how much is code vs tests, the agent sessions and decisions behind it, CI results, and what a human must check first — as one interactive HTML page. Use when asked to review, assess or summarise an agent branch or PR, "is this branch ready to merge", "what did the agent do on this branch", or to produce a branch, PR or impact report.
---

# Branch report

The report has two layers. Scripts compute the facts (diff, symbols, affected modules, config, tests, sessions, CI). You add the judgement in `report.json`: verdict, what to check first, scope, structure findings, test quality, decisions. The renderer merges both into one HTML page drawn on the project map.

## The CLI

`ATLAS` below means `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/atlas_cli.py"`. If that placeholder was not filled in, use `python3 "${CLAUDE_SKILL_DIR}/../../scripts/atlas_cli.py"`; if neither exists, Glob for `**/project-atlas/scripts/atlas_cli.py` under `~/.claude` and use the newest. Run it inside the repository.

All commands default to the current branch compared with its merge base on main. For another branch, pass `--head <branch>` (and `--base <ref>` if main is not the base) to every command. Outputs go to the folder printed by `ATLAS report-dir` (inside `.git/`, so nothing is added to the working tree).

## 1. Collect facts

```
ATLAS impact          # diff, lines by kind, symbols, affected modules, config, deps, tests, commits
ATLAS sessions        # agent sessions for this branch: trailers, summaries, local transcripts
ATLAS ci              # CI checks via gh (skip silently if unavailable)
ATLAS baseline        # tests-to-source ratio of recent human changes, for comparison
```

`impact.json` is large. Read the parts you need with python or jq, for example `modules` (status, symbol changes, `reasons` for affected modules), `config`, `external`, `tests`, `edges`, `pins`, `commits`.

If the repo has no `.project-map/`, the report still works with automatic grouping by directory. Mention that the project-map skill would add business areas, flows and pinned notes.

## 2. Read

- **The task.** The first prompt of the first session (`sessions.json`), the PR description (`gh pr view <branch>`), or ask the user. Without a task you cannot judge scope; say so in the report.
- **The diff.** `git diff <merge_base>..<head>`, source and config first, then tests. Read every changed source file in full around the changes, not only the hunks.
- **The sessions.** For each session with a `transcript_path`, run `ATLAS transcript <path>` for a condensed log (prompts, replies, tool calls). Look for: decisions and the alternatives dropped, assumptions, places the human corrected the agent, reverts, tests skipped or deleted to get green, and work the agent said it would do but did not.
- **Affected modules.** For each module with status `affected`, open the caller and confirm whether the change really breaks or alters it. Callers that only `imports` the module are possible impacts; confirm or drop them.

## 3. Write report.json

Write it to the report folder. The schema, with an example, is in `references/report-json.md`. Every field is optional; leave out what you could not assess.

What to look for:
- **attention**: what a reviewer must check before merging, most serious first. Typical items: behaviour changes callers depend on (exceptions, return values, timing), changes outside the task, tests skipped, deleted or weakened, new dependencies, shared config changes, contradicted pins, security-sensitive code, new branches without tests. Give each a `where` (file:line or commit).
- **scope**: requested items with done / partial / missing, extra work, and what is missing.
- **structure**: duplicated code and missed reuse (search the repo for existing helpers doing the same thing), abstractions with a single use, dependencies in the wrong direction. Add `edges` (`{"from", "to", "kind": "miss"}`) so the map draws them.
- **pin_checks**: one entry per pin in `impact.json` `pins`: does the branch respect it?
- **tests.classification**: what the new tests check (behaviour, duplicates that could be parametrised, assertions on mocks only, tests of a third-party library, skipped), with counts and advice. Optional `mutation`: run it only if the user asks, or if tests far outweigh source and a quick check is cheap (remove or break the new logic, run the new tests, restore). Report how many new tests failed.
- **decisions**: choices that shaped the branch, from transcripts and `Agent-Decision` trailers, with the reasons and the alternatives dropped.
- **review_order**, **file_notes**, **module_notes**: help the reviewer read the diff.
- **verdict**: `ready`, `review` (mergeable after a human checks the attention items) or `block`, with a short headline and a one-sentence summary.

Rules:
- Every claim must be checkable: cite file:line, commit or session. Numbers come from the scripts; do not compute your own.
- Say what you could not verify (no task, no transcripts, CI unavailable) instead of guessing.
- Transcripts can contain secrets and personal data. Summarise; quote only short phrases a reviewer needs.
- Write in the repository's language (`atlas.json` `language`) or the language the user writes in; set `language` in report.json.

## 4. Render and deliver

`ATLAS render report` validates report.json (fix what it reports and run it again) and writes `report.html` in the report folder: one self-contained file.

If you can publish HTML pages (for example an artifact tool that wraps pages in its own document), run `ATLAS render report --fragment --out <path>` and publish that file. Otherwise give the user the file path.

In chat, give the verdict, the top attention items (one line each) and the link or path. Keep the details in the report.
