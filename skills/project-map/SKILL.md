---
name: project-map
description: Build, update or show the project map in .project-map/ — a maintained picture of the repository's modules, layers, business areas, flows and dependencies, with an AI-written page per module and notes people pin, rendered as an interactive HTML map. Use when asked to set up, create, update, refresh, check or show the project map, architecture map or codebase overview, when running after a merge to main in CI, or when `atlas check` reports problems.
---

# Project map

You maintain `.project-map/` in the repository. It has four kinds of content, and each has one owner:

| File | What | Who writes it |
|---|---|---|
| `map.json` | Facts: modules, sizes, dependencies, callers, config readers, owners | the `facts` command only; never edit by hand |
| `atlas.json` | Structure: layers, groups (business areas), flows, key external packages | you propose, people review |
| `modules/<slug>.md` | One explanation page per module | you |
| `pins.md` | Rules, contracts, decisions pinned to modules | people only; never edit it |

`map.html` is the rendered page. File formats are in `references/format.md`; read it before writing atlas.json or module pages.

## The CLI

`ATLAS` below means `python3 <plugin root>/scripts/atlas_cli.py`. The plugin root is two folders above this SKILL.md. Resolve it in this order:
1. Claude Code: `${CLAUDE_PLUGIN_ROOT}/scripts/atlas_cli.py`, or `${CLAUDE_SKILL_DIR}/../../scripts/atlas_cli.py`.
2. pi and omp: the directory this SKILL.md was loaded from (omp states it as `[Skill directory: ...]`), plus `../../scripts/atlas_cli.py`.
3. If a placeholder above was left unfilled or the file is missing, search for `**/project-atlas/scripts/atlas_cli.py` under `~/.claude`, `~/.pi`, `~/.omp` and the global `node_modules`, and use the newest match.

Quote the path if it contains spaces. `ATLAS --help` must print a usage line; if it cannot open the file, the path is wrong. Run it from inside the repository. It needs only git and python3 (3.8+).

## Pick the mode

- No `.project-map/atlas.json` → **Set up** (A).
- It exists → **Update** (B). This is also what CI runs after each merge to main.
- The user only wants to see the map and `map.json` is for the current main → just **Render** (C).

## A. Set up

1. `ATLAS init --language <code>`. Use the language the user writes in (`zh-CN`, `en`, ...); every page and explanation is written in it.
2. `ATLAS facts`, then `ATLAS summary`. The summary lists directories, modules, cross-directory dependencies, external packages and config readers.
3. Read the summary, the README and the main entry points (routers, CLI, job schedulers). Then write `atlas.json`:
   - **layers**: 3–4 bands from entry points down to infrastructure (for example entry → business areas → infrastructure). Order matters: first is drawn on top.
   - **groups**: one per business area in the product's own vocabulary ("Merchant notifications", "Payouts"), not one per folder. Technical layers like `infra/` or `utils/` can stay as their folder name. Give each group `include` globs and a one-sentence `about`. Every module must land in exactly one group.
   - **flows**: 3–8 flows a new engineer would need to understand (a request, a job, a money movement). Each is one or more chains of module ids in call order. Trace each hop in the code; do not guess from file names.
   - **external**: up to 8 third-party packages that matter architecturally (HTTP client, queue, ORM). Leave out utilities.
4. `ATLAS check`. Fix every error, then the "match no group" warnings. Repeat until it is clean apart from missing pages.
5. Write the module pages (section "Writing a module page"). `ATLAS stale` lists them. Work group by group.
6. Render (C), then tell the user: the groups and flows you chose, anything you were unsure about (they should review atlas.json), and rules you noticed that belong in `pins.md`. Suggest pins; do not write them.

## B. Update

1. `ATLAS facts` (scans the main branch, not the working tree).
2. `ATLAS check` and fix structure: add new modules to a group's `include` (or add a group if a new business area appeared), drop flow hops to modules that no longer exist, re-trace flows whose code changed.
3. `ATLAS stale` and act on each line:
   - `missing` → write the page.
   - `changed` → rewrite the page in place.
   - `major` (changed more than the threshold) → write the new version to `ATLAS page-path <id> --pending`. Leave the current page alone; the owner approves with `ATLAS approve <id>`.
   - `pending` → leave it.
   - `orphan` → delete the page file.
4. If code now contradicts a pin in `pins.md`, say so in your summary. Do not change the pin or bend the explanation to match it.
5. Render (C). Summarise what changed on the map: new or removed modules, new links between groups, flows you re-traced, pages waiting for approval.
6. Commit only when asked (CI does this, see the plugin README). Commit `.project-map/` only.

## C. Render

`ATLAS render map` writes `.project-map/map.html`, a single self-contained file. When you will publish it through a tool that wraps pages in its own `<html>` document, add `--fragment --out <path>` and publish that file. Otherwise give the user the path.

## Writing a module page

Get the path from `ATLAS page-path <module id>`. The frontmatter values come from `map.json`: `rev` is its top-level `rev`, `hash` is `modules[<id>].hash`. A page whose hash no longer matches is shown as possibly stale, so copy them exactly.

The body is 1–4 sentences, at most about 80 words:
- What the module is for, in business terms, and its role in the flows that pass through it.
- Behaviour a reader would not guess: side effects, invariants, ordering, what happens on failure.
- Skip what the page already shows as facts (size, callers, dependencies, owners).

Read the code before writing; cite the lines you relied on in `refs` (for example `delivery.py:12-74`). Do not describe intent you cannot see in the code.

## Rules

- Never edit `map.json` or `pins.md` by hand.
- Facts come from the scripts. Do not add numbers of your own to pages or atlas.json.
- Keep group and flow ids stable across updates; reports and links depend on them.
- Large repos: `facts` switches to one module per directory above 150 source files. Set `"scan": {"granularity": "file"}` in atlas.json only if the user wants file-level detail.
