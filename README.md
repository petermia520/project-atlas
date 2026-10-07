# Project Atlas

A plugin for Claude Code, pi and oh-my-pi (omp) with two skills that share one set of scripts:

- **project-map**: keeps a map of your repository in `.project-map/`. It shows modules arranged by layer and business area, the business flows drawn across them, dependencies, a short AI-written page per module, and notes people pin to modules. It renders as one interactive HTML page.
- **branch-report**: reviews a branch, especially one an agent wrote. It covers what changed, what the change affects across the project map, how much is code vs tests, the agent sessions and decisions behind it, CI, and what a person must check before merging. It renders as one HTML page with the branch drawn on the project map.

Everything that can be computed is computed by scripts (git, Python `ast`, regex for JS/TS). The agent adds only judgement: explanations, verdicts, scope, test quality, decisions. Each part of a page is labelled with where it came from: computed, AI-written or human note.

## Install

From a clone of this repository:

```bash
claude plugin marketplace add /path/to/project-atlas
claude plugin install project-atlas@project-atlas
```

Or load it for one session without installing: `claude --plugin-dir /path/to/project-atlas`.

### pi and oh-my-pi

The same repository is also a pi package (`package.json` → `pi`) and an omp plugin (omp reads the Claude Code marketplace format and `package.json` → `omp`).

```bash
# pi
pi install git:github.com/<you>/project-atlas
# or for one run:
pi -e /path/to/project-atlas/extensions/project-atlas.ts \
   --skill /path/to/project-atlas/skills/project-map --skill /path/to/project-atlas/skills/branch-report

# oh-my-pi
omp plugin marketplace add <you>/project-atlas
omp plugin install project-atlas@project-atlas
# or for one run:
omp --plugin-dir /path/to/project-atlas
```

In pi, run a skill with `/skill:project-map` or `/skill:branch-report`, or just ask. What differs from Claude Code:

| | Claude Code | pi / omp |
|---|---|---|
| Session start and end | `hooks/hooks.json` | `extensions/project-atlas.ts` (same behaviour) |
| Git branch in transcripts | recorded by Claude Code | not recorded; the extension writes `project-atlas.branch` entries into the session file |
| Sessions without branch info | — | matched to a branch by working folder and commit times, and labelled "matched by time" in the report |
| Cost | not recorded | recorded per message, summed in the report |

Session files are read from `~/.pi/agent/sessions/` and `~/.omp/agent/sessions/` (and omp profiles). `PI_AGENT_DIR`, `PI_CODING_AGENT_DIR`, `PI_CODING_AGENT_SESSION_DIR` and `PI_CONFIG_DIR` are respected; `ATLAS_PI_SESSIONS` / `ATLAS_OMP_SESSIONS` point the scripts at other folders. Set `ATLAS_PYTHON` if `python3` is not the right interpreter for the extension.

For agents with no extension at all, put the trailer convention in `AGENTS.md`: `python3 scripts/atlas_cli.py agent-context --agents-md` prints a snippet.

Requirements: `git` and `python3` 3.8 or newer. The scripts use only the standard library. `gh` is optional and only used for CI results.

## Use

In Claude Code, inside your repository:

- "Set up the project map" or `/project-atlas:project-map`. The first run proposes `atlas.json` (layers, business areas, flows) and writes module pages. Review `atlas.json` and add rules to `.project-map/pins.md`.
- "Update the project map": run after merges. CI can do this; see `examples/update-map.yml`.
- "Review this branch" or `/project-atlas:branch-report`: writes the report for the current branch. Add a branch name to review another one.

The report works without a project map. It then groups modules by directory and has no business flows or pinned notes.

## What gets stored where

| Path | Content | Written by | Committed |
|---|---|---|---|
| `.project-map/atlas.json` | layers, groups, flows, scan settings | agent proposes, people review | yes |
| `.project-map/map.json` | facts for main | `atlas facts` | yes |
| `.project-map/modules/*.md` | one explanation per module (`*.pending.md` = rewrite awaiting the owner) | agent | yes |
| `.project-map/pins.md` | rules and decisions pinned to modules | people only | yes |
| `.project-map/map.html` | rendered map | `atlas render map` | your choice |
| `.git/atlas/reports/<branch>/` | `impact.json`, `sessions.json`, `report.json`, `report.html` | scripts and agent | no (inside `.git`) |
| `.git/atlas/sessions/<id>.json` | session summaries | SessionEnd hook | no |

## Agent sessions

A branch report links commits to the agent sessions behind them. It looks in four places, most reliable first:

1. **Commit trailers.** In repos with `.project-map/atlas.json`, the SessionStart hook (Claude Code) or the extension (pi, omp) tells the agent its session id and asks it to end commits with `Agent-Session:`, `Agent-Decision:` and `Agent-Assumption:` trailers. They travel with git, so every reviewer sees them.
2. **git notes** (opt-in). With `ATLAS_GIT_NOTES=1` in the agent's environment, the SessionEnd hook appends a session summary to `refs/notes/atlas-sessions`. Share them with `git push origin refs/notes/atlas-sessions` and fetch with `git fetch origin refs/notes/atlas-sessions:refs/notes/atlas-sessions`.
3. **Session summaries.** The SessionEnd hook or the extension writes one per session into `.git/atlas/sessions/`. They are kept after Claude Code removes old transcripts, but stay on the machine where the agent ran.
4. **Transcripts** in `~/.claude/projects/`, `~/.pi/agent/sessions/` and `~/.omp/agent/sessions/`, while they exist on this machine. Claude Code deletes its transcripts after `cleanupPeriodDays` (30 by default).

Summaries contain the first prompt, later human messages (each cut to 400 characters), tool counts, token counts and the files edited. Transcripts can contain secrets. The report quotes only short excerpts, and git notes are off by default.

## Run in CI

- `examples/update-map.yml` runs after every merge to main. It updates the facts, lets Claude rewrite only the pages for changed modules, and opens a pull request with the `.project-map/` changes.
- `examples/branch-report.yml` writes a report for agent pull requests and uploads it as a build artifact. In CI only trailers and git notes are available, not local transcripts.

The examples call `claude -p`. With pi or omp, use `pi -p "..." -e <extension> --skill <dir>` or `omp -p "..." --plugin-dir <dir>` instead.

Facts alone need no model: `python3 scripts/atlas_cli.py facts && python3 scripts/atlas_cli.py render map`.

## CLI

`python3 scripts/atlas_cli.py <command> --help` gives details.

| Command | Does |
|---|---|
| `init` | create `.project-map/` with an empty `atlas.json` and `pins.md` |
| `facts [--rev main] [--coverage]` | scan a revision into `map.json` |
| `summary` | compact text overview of the facts (for proposing groups and flows) |
| `check` | validate `atlas.json`, flows, pages and pins against the facts |
| `stale` | pages to write (`missing`), rewrite (`changed`), rewrite for approval (`major`), approve (`pending`) or delete (`orphan`) |
| `page-path <module> [--pending]` | where a module's page lives |
| `approve <module>` | promote a pending page |
| `report-dir` | the report folder for the current branch |
| `impact [--base] [--head]` | diff, symbols, affected modules, config, dependencies, tests, commits |
| `sessions [--all-projects]` | agent sessions behind the branch |
| `transcript <path>` | readable log of one session transcript |
| `ci` | CI checks through `gh` |
| `baseline [--days 90]` | test-to-source ratio of recent human changes |
| `agent-context [--session-id] [--agents-md]` | the commit-trailer instructions agents get, or an AGENTS.md snippet |
| `render map\|report [--fragment] [--out]` | write the HTML page; `--fragment` leaves out `<html>`/`<head>`/`<body>` for hosts that add their own |

## What the analysis covers

- **Python**: full analysis with `ast`: imports resolved to files (absolute, relative, `src/` layouts), names used per import, functions and classes, signatures, cyclomatic complexity, docstrings.
- **JavaScript / TypeScript**: imports, `require`, `tsconfig` path aliases, top-level functions and classes. This uses regular expressions, so treat it as approximate.
- **Other languages**: line counts and change counts only, with no dependency edges. Add an analyzer in `scripts/atlas/langs.py` to support another language.
- **Config readers** are found by searching code for key paths: `"webhook.timeout_ms"`, `settings["webhook"]["timeout_ms"]`, `.webhook.timeout_ms`, and environment variable names. A reader the search misses will not show as affected.
- **Impact** goes one step from the change: callers that use a changed or removed symbol, and readers of changed config. It does not follow callers of callers.
- **Size**: above 150 source files, the map switches to one module per directory (at most 3 levels deep). Django scans in about 9 seconds.

## Develop

```bash
python3 -m unittest discover -s tests -v          # end-to-end tests on a generated repo
python3 tests/fixture.py /tmp/atlas-demo           # a demo repo with an agent branch
node tests/extension_check.mjs <repo> <branch>   # drive the pi/omp extension with a fake runtime (the unit tests do this)
NODE_PATH=<dir with jsdom> node tests/dom_check.js page.html   # exercise a rendered page headlessly
claude plugin validate --strict .
```
