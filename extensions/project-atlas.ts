/**
 * Project Atlas extension for pi and oh-my-pi (omp).
 *
 * Does for pi/omp what hooks/hooks.json does for Claude Code:
 *  - In repos with .project-map/atlas.json (or ATLAS_TRAILERS=1), adds the commit-trailer
 *    convention and the session id to the system prompt.
 *  - Records the current git branch in the session file as `project-atlas.branch` custom
 *    entries, because pi/omp transcripts do not store it and branch reports need it.
 *  - When the session ends, saves a session summary into .git/atlas/sessions/ (hooks/session_end.py).
 *
 * Written without type annotations so it loads as TypeScript (pi via jiti, omp via Bun) and as plain JS.
 * Every handler swallows its own errors: the extension must never break a session.
 */
import { closeSync, existsSync, openSync, readSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = typeof __dirname === "string" ? __dirname : dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const CLI = join(ROOT, "scripts", "atlas_cli.py");
const SESSION_END = join(ROOT, "hooks", "session_end.py");
const BRANCH_ENTRY = "project-atlas.branch";
const AGENT = process.versions && process.versions.bun ? "omp" : "pi";
const PYTHON = process.env.ATLAS_PYTHON || "python3";

function attempt(fn) {
  try {
    return fn();
  } catch (_err) {
    return undefined;
  }
}

function headerId(file) {
  // The first line of a pi/omp session file is {"type":"session","id":...}.
  return attempt(() => {
    const fd = openSync(file, "r");
    const buf = Buffer.alloc(4096);
    const n = readSync(fd, buf, 0, buf.length, 0);
    closeSync(fd);
    return JSON.parse(buf.toString("utf8", 0, n).split("\n")[0]).id;
  });
}

export default function projectAtlas(pi) {
  let state = null;

  async function run(cmd, args, cwd, timeout) {
    try {
      const r = await pi.exec(cmd, args, { cwd, timeout: timeout || 5000 });
      return r && r.code === 0 ? String(r.stdout || "").trim() : null;
    } catch (_err) {
      return null;
    }
  }

  async function ensure(ctx) {
    const cwd = (ctx && ctx.cwd) || process.cwd();
    const sm = ctx && ctx.sessionManager;
    const file = sm ? attempt(() => sm.getSessionFile()) : undefined;
    if (state && state.cwd === cwd && state.file === file) return state;
    const root = await run("git", ["rev-parse", "--show-toplevel"], cwd);
    state = { cwd, file, root, branch: null, context: null, enabled: false, id: undefined };
    if (!root) return state;
    state.id = (sm && attempt(() => sm.getSessionId())) || (file && headerId(file)) || undefined;
    state.enabled = existsSync(join(root, ".project-map", "atlas.json")) || process.env.ATLAS_TRAILERS === "1";
    return state;
  }

  async function noteBranch(ctx) {
    try {
      const s = await ensure(ctx);
      if (!s.root) return;
      const branch = await run("git", ["rev-parse", "--abbrev-ref", "HEAD"], s.root);
      if (!branch || branch === s.branch) return;
      s.branch = branch;
      await pi.appendEntry(BRANCH_ENTRY, { branch, at: new Date().toISOString() });
    } catch (_err) {
      // ephemeral sessions cannot store entries; nothing to record
    }
  }

  async function record(reason) {
    const s = state;
    if (!s || !s.root || !s.file) return;
    const payload = JSON.stringify({ session_id: s.id, transcript_path: s.file, cwd: s.root, reason, agent: AGENT });
    await run(PYTHON, [SESSION_END, "--payload", payload], s.root, 30000);
  }

  pi.on("session_start", async (_event, ctx) => { await noteBranch(ctx); });
  pi.on("agent_start", async (_event, ctx) => { await noteBranch(ctx); });
  pi.on("tool_result", async (_event, ctx) => { await noteBranch(ctx); });
  pi.on("agent_end", async (_event, ctx) => { await noteBranch(ctx); });

  pi.on("before_agent_start", async (event, ctx) => {
    try {
      const s = await ensure(ctx);
      if (!s.root || !s.enabled) return undefined;
      if (s.context === null) {
        s.context = (await run(PYTHON, [CLI, "agent-context", "--session-id", s.id || "<your session id>"], s.root)) || "";
      }
      if (!s.context) return undefined;
      return { systemPrompt: ((event && event.systemPrompt) || "") + "\n\n" + s.context };
    } catch (_err) {
      return undefined;
    }
  });

  pi.on("session_shutdown", async (event) => {
    try {
      await record(event && event.reason);
    } catch (_err) {
      // never block shutdown
    }
  });
}
