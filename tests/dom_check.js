#!/usr/bin/env node
/* Loads rendered pages in jsdom, exercises every control, and fails on script errors,
   NaN/undefined in SVG geometry, or overlapping groups.
   Usage: NODE_PATH=<dir with jsdom> node tests/dom_check.js page.html [more.html] */
"use strict";
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

let failures = 0;
function fail(file, msg) { failures++; console.error("FAIL " + file + ": " + msg); }

function geometryProblems(doc) {
  const bad = [];
  doc.querySelectorAll("svg *").forEach((el) => {
    for (const a of ["x", "y", "width", "height", "d", "cx", "cy", "viewBox"]) {
      const v = el.getAttribute(a);
      if (v != null && /NaN|undefined|Infinity/.test(v)) bad.push(el.tagName + "[" + a + "]=" + v.slice(0, 60));
    }
  });
  return bad;
}

function overlaps(doc) {
  const rects = [...doc.querySelectorAll("svg rect.grp, svg .grpn rect")].map((r) => ({
    x: +r.getAttribute("x"), y: +r.getAttribute("y"), w: +r.getAttribute("width"), h: +r.getAttribute("height") }));
  const out = [];
  for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
    const a = rects[i], b = rects[j];
    if (a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) out.push([a, b]);
  }
  return out;
}

for (const file of process.argv.slice(2)) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(e.message + (e.detail ? " " + e.detail : "")));
  vc.on("error", (e) => errors.push(String(e)));
  const dom = new JSDOM(fs.readFileSync(file, "utf8"), { runScripts: "dangerously", virtualConsole: vc, pretendToBeVisual: true });
  const { window } = dom, doc = window.document;
  window.HTMLElement.prototype.scrollIntoView = function () {};
  const click = (el) => el && el.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  const step = (name, fn) => { try { fn(); } catch (e) { errors.push(name + ": " + e.stack); } };

  const nodes = doc.querySelectorAll("svg .node");
  if (!nodes.length) fail(file, "no map nodes rendered");
  step("click every node", () => doc.querySelectorAll("svg .node").forEach((n) => { click(n); click(n); }));
  step("hover", () => { const n = doc.querySelector("svg .node"); n.dispatchEvent(new window.MouseEvent("mouseenter")); n.dispatchEvent(new window.MouseEvent("mouseleave")); });
  step("panel chips", () => {
    click(doc.querySelector("svg .node"));
    doc.querySelectorAll(".side [data-go]").forEach((b, i) => { if (i < 5) click(b); });
    click(doc.querySelector(".side [data-back]"));
  });
  step("flows", () => doc.querySelectorAll(".fchips [data-flow]").forEach((b) => { click(b); click(b); }));
  step("view toggle", () => {
    click(doc.querySelector('[data-ctl="view"] [data-v="domain"]'));
    if (overlaps(doc).length) fail(file, "groups overlap in group view");
    doc.querySelectorAll("svg .node").forEach((n) => click(n));
    click(doc.querySelector('[data-ctl="view"] [data-v="module"]'));
  });
  step("overlay toggle", () => {
    const off = doc.querySelector('[data-ctl="overlay"] [data-v="off"]');
    if (off) { click(off); doc.querySelectorAll("svg .node").forEach((n) => click(n)); click(doc.querySelector('[data-ctl="overlay"] [data-v="on"]')); }
  });
  step("layers", () => doc.querySelectorAll("input[data-ctl]").forEach((c) => { c.checked = !c.checked; c.dispatchEvent(new window.Event("change", { bubbles: true })); }));
  step("default panel buttons", () => doc.querySelectorAll(".side [data-go], .side [data-grp], .side [data-flow]").forEach((b, i) => { if (i < 8) { click(b); click(doc.querySelector(".side [data-back]")); } }));
  step("report controls", () => {
    doc.querySelectorAll("#attn button").forEach((b) => click(b));
    doc.querySelectorAll("#file-filter button").forEach((b) => click(b));
    doc.querySelectorAll("#files input").forEach((c) => { c.checked = true; c.dispatchEvent(new window.Event("change", { bubbles: true })); });
    doc.querySelectorAll("#structure [data-go]").forEach((b) => click(b));
  });
  const geo = geometryProblems(doc);
  if (geo.length) fail(file, "bad SVG geometry: " + geo.slice(0, 5).join("; "));
  if (overlaps(doc).length) fail(file, "groups overlap in module view");
  const text = doc.getElementById("app").textContent;
  const raw = text.match(/\b[a-z]+_[a-z_]+\b/g) || [];
  const keys = new Set(Object.keys(window.AtlasI18n.dicts.en));
  const leaked = [...new Set(raw.filter((w) => keys.has(w)))];
  if (leaked.length) fail(file, "untranslated keys shown: " + leaked.join(", "));
  errors.forEach((e) => fail(file, e));
  console.log((errors.length ? "errors " : "ok ") + file + " · " + nodes.length + " nodes · " + doc.querySelectorAll("svg .edge").length + " edges · " + doc.querySelectorAll("svg .fl").length + " flow paths");
}

// Every i18n key exists in both languages.
const i18n = require("../templates/i18n.js");
const en = Object.keys(i18n.dicts.en), zh = new Set(Object.keys(i18n.dicts.zh));
const missing = en.filter((k) => !zh.has(k));
if (missing.length) fail("i18n.js", "missing zh keys: " + missing.join(", "));
const extra = [...zh].filter((k) => !(k in i18n.dicts.en));
if (extra.length) fail("i18n.js", "zh keys missing in en: " + extra.join(", "));
process.exit(failures ? 1 : 0);
