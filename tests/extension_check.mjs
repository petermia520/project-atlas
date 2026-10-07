#!/usr/bin/env node
// Drives extensions/project-atlas.ts with a fake pi/omp runtime against a real git repo.
// Usage: node tests/extension_check.mjs <repo> <branch>
// Checks: branch entries are written when the branch changes, the trailer text reaches the
// system prompt, and session_shutdown leaves a summary in .git/atlas/sessions/.
import { spawnSync } from "node:child_process";
import { appendFileSync, copyFileSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const [repo, branch] = process.argv.slice(2);
const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "extensions", "project-atlas.ts");
const copy = join(here, "..", "extensions", ".check-" + process.pid + ".mjs");
copyFileSync(src, copy);
let failures = 0;
const check = (ok, msg) => { if (!ok) { failures++; console.error("FAIL " + msg); } };

try {
  const { default: factory } = await import(copy);
  const dir = mkdtempSync(join(tmpdir(), "atlas-ext-"));
  const sessionId = "ext-session-1";
  const file = join(dir, "s.jsonl");
  let n = 0;
  const line = (obj) => appendFileSync(file, JSON.stringify(Object.assign({ id: (++n).toString(16).padStart(8, "0"), parentId: null, timestamp: new Date().toISOString() }, obj)) + "\n");
  writeFileSync(file, JSON.stringify({ type: "session", version: 3, id: sessionId, timestamp: new Date().toISOString(), cwd: repo }) + "\n");

  const handlers = {};
  const entries = [];
  const pi = {
    on: (event, fn) => { handlers[event] = fn; },
    exec: async (cmd, args, opts) => {
      const r = spawnSync(cmd, args, { cwd: opts && opts.cwd, encoding: "utf8", timeout: opts && opts.timeout });
      return { stdout: r.stdout, stderr: r.stderr, code: r.status, killed: false };
    },
    appendEntry: async (customType, data) => { entries.push({ customType, data }); line({ type: "custom", customType, data }); },
  };
  factory(pi);
  const ctx = { cwd: repo, sessionManager: { getSessionFile: () => file, getSessionId: () => sessionId } };
  const git = (...args) => spawnSync("git", ["-C", repo, ...args], { encoding: "utf8" });

  for (const ev of ["session_start", "before_agent_start", "tool_result", "session_shutdown"]) check(typeof handlers[ev] === "function", "handles " + ev);

  git("checkout", "-q", "main");
  await handlers.session_start({ reason: "startup" }, ctx);
  check(entries.length === 1 && entries[0].data.branch === "main", "records the starting branch");

  const res = await handlers.before_agent_start({ systemPrompt: "BASE", prompt: "hi" }, ctx);
  check(res && res.systemPrompt.startsWith("BASE") && res.systemPrompt.includes("Agent-Session: " + sessionId), "adds trailer instructions to the system prompt");

  line({ type: "message", message: { role: "user", content: "Add retries to delivery." } });
  git("checkout", "-q", branch);
  await handlers.tool_result({ toolName: "bash" }, ctx);
  await handlers.tool_result({ toolName: "read" }, ctx);
  check(entries.length === 2 && entries[1].data.branch === branch, "records a branch switch once");
  line({ type: "message", message: { role: "assistant", model: "m", content: [{ type: "toolCall", id: "c", name: "edit", arguments: { path: "payments/webhooks/delivery.py" } }],
         usage: { input: 10, output: 5, cost: { total: 0.001 } } } });

  await handlers.session_shutdown({ reason: "quit" }, ctx);
  const common = git("rev-parse", "--git-common-dir").stdout.trim();
  const saved = join(common.startsWith("/") ? common : join(repo, common), "atlas", "sessions", sessionId + ".json");
  check(existsSync(saved), "writes a session summary on shutdown");
  if (existsSync(saved)) {
    const rec = JSON.parse(readFileSync(saved, "utf8"));
    const s = rec.by_branch[branch];
    check(rec.agent === "pi", "labels the agent");
    check(s && s.files_touched.includes("payments/webhooks/delivery.py") && s.task === "Add retries to delivery.", "summary is attributed to the new branch");
    rmSync(saved, { force: true });
  }

  // Outside a git repository the extension stays silent.
  const quiet = await handlers.before_agent_start({ systemPrompt: "BASE" }, { cwd: dir, sessionManager: { getSessionFile: () => undefined } });
  check(quiet === undefined, "does nothing outside a repository");
  rmSync(dir, { recursive: true, force: true });
} finally {
  rmSync(copy, { force: true });
}
console.log(failures ? failures + " failures" : "ok extension");
process.exit(failures ? 1 : 0);
