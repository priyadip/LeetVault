/* A DOM stub strict enough to catch what a lenient one hides.
 *
 * The rule that matters: getElementById returns an element only while it is attached. A
 * stub that hands back a fresh object for any id will happily "find" a node that the code
 * just detached, which is precisely the bug this exists to catch. */
import { readFileSync } from "node:fs";

const registry = new Map();

function makeEl(id = "", tag = "div") {
  const el = {
    id,
    tagName: tag.toUpperCase(),
    dataset: {},
    style: {},
    attached: true,
    hidden: false,
    textContent: "",
    innerHTML: "",
    value: "",
    children: [],
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); },
      remove(c) { this._set.delete(c); },
      contains(c) { return this._set.has(c); },
      toggle(c, on) { on === undefined ? (this._set.has(c) ? this._set.delete(c) : this._set.add(c)) : (on ? this._set.add(c) : this._set.delete(c)); },
    },
    append(...kids) { kids.forEach((k) => { k.attached = true; el.children.push(k); }); },
    replaceChildren(...kids) { el.children = []; el.append(...kids); },
    remove() { el.attached = false; },
    addEventListener() {},
    removeEventListener() {},
    setPointerCapture() {},
    querySelectorAll() { return []; },
    getBoundingClientRect() { return { width: 100, height: 100 }; },
    closest() { return null; },
    get className() { return [...this.classList._set].join(" "); },
    set className(v) { this.classList._set = new Set(String(v).split(/\s+/).filter(Boolean)); },
    get previousElementSibling() { return null; },
    get nextElementSibling() { return null; },
    get flexGrow() { return this.style.flexGrow; },
  };
  return el;
}

const ids = [
  "rail", "rail-toggle", "rail-show", "theme-toggle", "repo-title", "repo-link",
  "view-on-github", "generated", "stats", "q", "f-topic", "f-diff", "f-lang", "rows",
  "count", "tbl", "view-problems", "view-problem", "view-course", "view-settings",
  "p-title", "p-diff", "p-topics", "p-leetcode", "c-meta", "q-body", "c-body", "a-body",
  "n-body", "n-edit", "btn-history", "btn-notes", "panes", "pane-q", "pane-c", "pane-a",
  "open-index", "close-index", "drawer", "drawer-q", "drawer-list", "drawer-scrim",
  "modal", "modal-scrim", "m-close", "m-title", "m-versions", "m-code", "prev", "next",
  "notes-modal", "notes-scrim", "n-close", "course-tree", "course-body", "course-md",
  "course-new", "set-theme", "set-code", "set-layout", "code-sample", "code-preview",
];
ids.forEach((id) => registry.set(id, makeEl(id)));

const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
};
globalThis.document = {
  // The whole point of this stub.
  getElementById: (id) => {
    const el = registry.get(id);
    return el && el.attached ? el : null;
  },
  createElement: (tag) => makeEl("", tag),
  querySelectorAll: () => [],
  documentElement: { dataset: {} },
  body: makeEl("body", "body"),
  activeElement: { tagName: "BODY" },
};
globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });
globalThis.addEventListener = () => {};
globalThis.location = { hash: process.env.BOOT_HASH || "#/problems" };
// node defines navigator as a getter, so patch the object it already exposes.
Object.defineProperty(globalThis.navigator, "clipboard", {
  value: { writeText: async () => {} }, configurable: true,
});
globalThis.fetch = async (path) => ({
  ok: true,
  text: async () => "## Approach\nhash map",
  json: async () => ({
    repo: "o/r",
    branch: "main",
    generated_at: "now",
    problems: [
      {
        id: 1, slug: "two-sum", title: "Two Sum", difficulty: "Easy", lang: "python3",
        ext: "py", url: "u", date: "2026-01-01", topics: ["Array"],
        has_analysis: true, has_notes: true,
        history: [{ file: "submission_9.py", id: 9 }],
      },
    ],
    course: [],
  }),
});

const src = readFileSync(process.env.APP_JS, "utf8");
await import("data:text/javascript," + encodeURIComponent(src));
await new Promise((r) => setTimeout(r, 80));

const hash = process.env.BOOT_HASH || "#/problems";
const expected = hash.startsWith("#/p/") ? "view-problem"
  : hash.startsWith("#/course") ? "view-course"
  : hash.startsWith("#/settings") ? "view-settings"
  : "view-problems";
const shown = registry.get(expected);
if (shown.hidden) {
  console.error("boot finished but no view was shown - route() never completed");
  process.exit(1);
}
console.log("ok");
