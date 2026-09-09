/* LeetVault site. Vanilla JS on purpose - see style.css for the reasoning.
 *
 * Everything is read from the repository itself at the paths sync already writes:
 * Problems/<slug>/question.md, latest.<ext>, analysis.md, notes.md, history/*. The
 * generated index.json is only a catalogue, so a file edited on GitHub shows up here
 * without regenerating anything.
 */
"use strict";

const $ = (id) => document.getElementById(id);
let DATA = { problems: [], course: [], repo: "" };
let VIEW = [];      // problems after search/filter, in display order
let CURRENT = null; // slug of the open problem

/* ---------- Markdown ---------------------------------------------------- */
/* Deliberately small and self-contained. It covers what these files actually contain -
 * headings, fenced code, tables, lists, emphasis, links, quotes - and escapes everything
 * first, because analysis.md is model-generated text and notes.md is free-form. */
function esc(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

function markdown(src) {
  const lines = (src || "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let i = 0, para = [];

  const flush = () => {
    if (para.length) { out.push("<p>" + inline(para.join(" ")) + "</p>"); para = []; }
  };

  while (i < lines.length) {
    const line = lines[i];

    const fence = line.match(/^```(\w*)/);
    if (fence) {                                   // fenced code
      flush();
      const body = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) body.push(lines[i++]);
      i++;
      out.push(`<pre><code class="code">${esc(body.join("\n"))}</code></pre>`);
      continue;
    }

    if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] || "")) {
      flush();                                     // table
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push("<table><thead><tr>" + head.map((h) => `<th>${inline(h)}</th>`).join("") +
        "</tr></thead><tbody>" +
        rows.map((r) => "<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>").join("") +
        "</tbody></table>");
      continue;
    }

    // LeetCode's hints arrive as <details>/<summary>, which GitHub renders natively.
    // Escaping them shows the reader raw markup, so exactly these three forms pass through
    // - they carry no scripting and no attributes - while every other tag stays escaped.
    if (/^\s*<details>\s*$/i.test(line)) { flush(); out.push("<details>"); i++; continue; }
    if (/^\s*<\/details>\s*$/i.test(line)) { flush(); out.push("</details>"); i++; continue; }
    const summary = line.match(/^\s*<summary>(.*)<\/summary>\s*$/i);
    if (summary) {
      flush();
      out.push(`<summary>${inline(summary[1])}</summary>`);
      i++;
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flush();
      out.push(`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`);
      i++; continue;
    }

    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {       // list
      flush();
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      // Stop when the marker type changes: a numbered list following a bulleted one is a
      // second list, and merging them renumbers content the author wrote deliberately.
      const sameKind = (l) => /^\s*([-*+]|\d+\.)\s+/.test(l) && /^\s*\d+\./.test(l) === ordered;
      while (i < lines.length && sameKind(lines[i])) {
        items.push(lines[i++].replace(/^\s*([-*+]|\d+\.)\s+/, ""));
      }
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>` + items.map((t) => `<li>${inline(t)}</li>`).join("") + `</${tag}>`);
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      flush();
      const quote = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push("<blockquote>" + markdown(quote.join("\n")) + "</blockquote>");
      continue;
    }

    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { flush(); out.push("<hr>"); i++; continue; }
    if (!line.trim()) { flush(); i++; continue; }

    para.push(line.trim());
    i++;
  }
  flush();
  return out.join("\n");
}

/* ---------- syntax highlighting ----------------------------------------- */
/* Hand-rolled for the same reason as the Markdown renderer: no CDN, no build step, still
 * working in five years. Correctness comes from the order of the alternation below -
 * comments and strings are matched first, so a keyword inside a string is never coloured
 * and a quote inside a comment never opens one. That single ordering is what separates a
 * tokenizer from a set of hopeful replacements. */
const KEYWORDS = {
  py: `False None True and as assert async await break class continue def del elif else
    except finally for from global if import in is lambda nonlocal not or pass raise return
    try while with yield match case`,
  java: `abstract assert boolean break byte case catch char class const continue default do
    double else enum extends final finally float for if implements import instanceof int
    interface long new package private protected public return short static super switch
    synchronized this throw throws try void volatile while var record true false null`,
  cpp: `auto bool break case catch char class const constexpr continue default delete do
    double else enum explicit export extern false float for friend goto if inline int long
    namespace new nullptr operator private protected public return short signed sizeof
    static struct switch template this throw true try typedef typename union unsigned using
    virtual void volatile while`,
  js: `async await break case catch class const continue debugger default delete do else
    export extends false finally for function if import in instanceof let new null return
    static super switch this throw true try typeof undefined var void while yield`,
  go: `break case chan const continue default defer else fallthrough for func go goto if
    import interface map package range return select struct switch type var nil true false`,
  rs: `as async await break const continue crate dyn else enum extern false fn for if impl
    in let loop match mod move mut pub ref return self static struct super trait true type
    unsafe use where while`,
};
KEYWORDS.c = KEYWORDS.cpp;
KEYWORDS.ts = KEYWORDS.js;
KEYWORDS.cs = KEYWORDS.java;
KEYWORDS.kt = KEYWORDS.java;
KEYWORDS.rb = KEYWORDS.py;

const keywordSet = (ext) => {
  const words = KEYWORDS[ext] || Object.values(KEYWORDS).join(" ");
  return new Set(words.split(/\s+/).filter(Boolean));
};

// Comments, then strings, then numbers, then decorators, then words. Order is the contract.
const TOKENS = new RegExp(
  [
    "(#[^\\n]*|//[^\\n]*|/\\*[\\s\\S]*?\\*/)",
    "(\"\"\"[\\s\\S]*?\"\"\"|'''[\\s\\S]*?'''|`(?:\\\\[\\s\\S]|[^`\\\\])*`" +
      "|\"(?:\\\\[\\s\\S]|[^\"\\\\\\n])*\"|'(?:\\\\[\\s\\S]|[^'\\\\\\n])*')",
    "(\\b\\d[\\w.]*)",
    "(@[A-Za-z_]\\w*)",
    "([A-Za-z_]\\w*)",
  ].join("|"),
  "g",
);

function highlight(code, ext) {
  const keywords = keywordSet(ext);
  let out = "";
  let last = 0;
  let match;
  TOKENS.lastIndex = 0;
  while ((match = TOKENS.exec(code)) !== null) {
    out += esc(code.slice(last, match.index));
    const [text, comment, string, number, decorator, word] = match;
    if (comment) out += `<span class="t-com">${esc(comment)}</span>`;
    else if (string) out += `<span class="t-str">${esc(string)}</span>`;
    else if (number) out += `<span class="t-num">${esc(number)}</span>`;
    else if (decorator) out += `<span class="t-dec">${esc(decorator)}</span>`;
    else if (keywords.has(word)) out += `<span class="t-key">${esc(word)}</span>`;
    else if (code[TOKENS.lastIndex] === "(") out += `<span class="t-fn">${esc(word)}</span>`;
    else out += esc(word);
    last = match.index + text.length;
  }
  return out + esc(code.slice(last));
}

/* ---------- fetching ---------------------------------------------------- */
const cache = new Map();
async function text(path) {
  if (cache.has(path)) return cache.get(path);
  const res = await fetch(path);
  const body = res.ok ? await res.text() : "";
  cache.set(path, body);
  return body;
}

const ghBlob = (p) => `https://github.com/${DATA.repo}/blob/${DATA.branch}/${p}`;
const ghEdit = (p) => `https://github.com/${DATA.repo}/edit/${DATA.branch}/${p}`;
const ghNew = (dir) => `https://github.com/${DATA.repo}/new/${DATA.branch}?filename=${dir}/new-section.md`;

/* ---------- problems list ----------------------------------------------- */
let sortKey = "id", sortAsc = true;

function applyFilters() {
  const q = $("q").value.trim().toLowerCase();
  const topic = $("f-topic").value, diff = $("f-diff").value, lang = $("f-lang").value;
  VIEW = DATA.problems.filter((p) =>
    (!q || p.title.toLowerCase().includes(q) || String(p.id).includes(q) || p.slug.includes(q)) &&
    (!topic || (p.topics || []).includes(topic)) &&
    (!diff || p.difficulty === diff) &&
    (!lang || p.lang === lang));
  VIEW.sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    const c = typeof x === "number" ? x - y : String(x).localeCompare(String(y));
    return sortAsc ? c : -c;
  });
  renderRows();
}

function renderRows() {
  $("rows").innerHTML = VIEW.map((p) => `
    <tr>
      <td>${p.id}</td>
      <td class="title"><a href="#/p/${p.slug}">${esc(p.title)}</a></td>
      <td><span class="pill ${p.difficulty}">${p.difficulty}</span></td>
      <td class="muted">${esc(p.lang || "")}</td>
      <td class="muted">${p.date || ""}</td>
      <td>${p.has_analysis ? '<span class="muted">yes</span>' : '<span class="muted">—</span>'}</td>
    </tr>`).join("");
  $("count").textContent = `${VIEW.length} of ${DATA.problems.length} problems`;
}

function renderStats() {
  const by = {};
  DATA.problems.forEach((p) => { by[p.difficulty] = (by[p.difficulty] || 0) + 1; });
  const analysed = DATA.problems.filter((p) => p.has_analysis).length;
  $("stats").innerHTML = [
    ["Problems", DATA.problems.length],
    ["Easy", by.Easy || 0], ["Medium", by.Medium || 0], ["Hard", by.Hard || 0],
    ["With analysis", analysed],
  ].map(([k, v]) => `<div class="stat"><b>${v}</b><span class="muted">${k}</span></div>`).join("");
}

/* ---------- one problem -------------------------------------------------- */
async function openProblem(slug) {
  const p = DATA.problems.find((x) => x.slug === slug);
  if (!p) return show("problems");
  CURRENT = slug;
  show("problem");

  $("p-title").textContent = `${p.id}. ${p.title}`;
  $("p-diff").textContent = p.difficulty;
  $("p-diff").className = `pill ${p.difficulty}`;
  $("p-topics").innerHTML = (p.topics || []).map((t) => `<span class="topic">${esc(t)}</span>`).join("");
  $("p-leetcode").href = p.url;
  $("c-meta").textContent = p.lang || "";

  const dir = `Problems/${slug}`;
  $("q-body").innerHTML = "<p class='muted'>Loading…</p>";
  const [question, code, analysis, notes] = await Promise.all([
    text(`${dir}/question.md`),
    text(`${dir}/latest.${p.ext}`),
    p.has_analysis ? text(`${dir}/analysis.md`) : Promise.resolve(""),
    p.has_notes ? text(`${dir}/notes.md`) : Promise.resolve(""),
  ]);
  $("q-body").innerHTML = markdown(question) || "<p class='muted'>No question.md yet.</p>";
  $("c-body").innerHTML = highlight(code, p.ext);
  $("a-body").innerHTML = markdown(analysis) ||
    "<p class='muted'>No analysis yet. Run <code>leetvault sync</code> with AI enabled.</p>";
  $("n-body").innerHTML = markdown(notes) || "<p class='muted'>Empty.</p>";
  $("n-edit").href = ghEdit(`${dir}/notes.md`);
  $("btn-history").textContent = `View history (${(p.history || []).length})`;
  $("btn-history").disabled = !(p.history || []).length;
  buildLayout(layoutName);
}

function neighbour(step) {
  const list = VIEW.length ? VIEW : DATA.problems;
  const idx = list.findIndex((p) => p.slug === CURRENT);
  const next = list[idx + step];
  if (next) location.hash = `#/p/${next.slug}`;
}

/* ---------- history modal ------------------------------------------------ */
async function openHistory() {
  const p = DATA.problems.find((x) => x.slug === CURRENT);
  if (!p) return;
  $("m-title").textContent = `Code history — ${p.title}`;
  $("modal").hidden = false;

  // Newest first: the latest attempt is what you almost always want to read.
  const versions = [{ label: "Latest", file: `Problems/${p.slug}/latest.${p.ext}`, date: p.date }]
    .concat((p.history || []).map((h) => ({
      label: `Submission ${h.id}`, file: `Problems/${p.slug}/history/${h.file}`, date: h.date || "",
    })));

  $("m-versions").innerHTML = versions.map((v, n) =>
    `<li data-n="${n}" class="${n === 0 ? "active" : ""}">
       <div>${esc(v.label)}</div><div class="muted sm">${esc(v.date || "")}</div></li>`).join("");
  const load = async (n) => {
    [...$("m-versions").children].forEach((li, k) => li.classList.toggle("active", k === n));
    $("m-code").innerHTML = highlight(await text(versions[n].file), p.ext);
  };
  $("m-versions").onclick = (e) => {
    const li = e.target.closest("li");
    if (li) load(Number(li.dataset.n));
  };
  load(0);
}

/* ---------- problem index drawer ---------------------------------------- */
function renderDrawer() {
  const q = $("drawer-q").value.trim().toLowerCase();
  const list = DATA.problems.filter((p) =>
    !q || p.title.toLowerCase().includes(q) || String(p.id).includes(q));
  $("drawer-list").innerHTML = list.map((p) =>
    `<a href="#/p/${p.slug}" class="${p.slug === CURRENT ? "active" : ""}">
       <span class="muted">${p.id}</span><span>${esc(p.title)}</span></a>`).join("");
}

/* ---------- course ------------------------------------------------------- */
function renderCourseTree(nodes, depth = 0) {
  if (!nodes.length) return "";
  return "<ul>" + nodes.map((n) => {
    const label = esc(n.title);
    const link = n.path
      ? `<a href="#/course/${encodeURIComponent(n.path)}">${label}</a>`
      : `<div class="sec">${label}</div>`;
    return `<li>${link}${renderCourseTree(n.children || [], depth + 1)}</li>`;
  }).join("") + "</ul>";
}

async function openCourse(path) {
  show("course");
  $("course-tree").innerHTML = DATA.course.length
    ? renderCourseTree(DATA.course)
    : "<p class='muted'>No sections yet.</p>";
  $("course-new").href = ghNew("Course");

  [...$("course-tree").querySelectorAll("a")].forEach((a) =>
    a.classList.toggle("active", decodeURIComponent(a.hash.split("/course/")[1] || "") === path));

  if (!path) {
    $("course-md").innerHTML = DATA.course.length
      ? "<p class='muted'>Pick a section on the left.</p>"
      : `<h1>My Course</h1><p>Add Markdown files under <code>Course/</code> in your
         repository and they appear here, nested by folder.</p>
         <p><a href="${ghNew("Course")}" target="_blank" rel="noopener">Create the first one</a></p>`;
    return;
  }
  const body = await text(path);
  $("course-md").innerHTML =
    `<div class="page-head"><span class="spacer"></span>
       <a class="btn ghost sm" href="${ghEdit(path)}" target="_blank" rel="noopener">Edit</a></div>` +
    (markdown(body) || "<p class='muted'>Empty section.</p>");
}

/* ---------- pane layout -------------------------------------------------- */
/* The three panes are arranged from a spec rather than fixed markup, so "two stacked on the
 * left, one down the right" is a different tree over the same elements - not a second set
 * of DOM. A spec is either a pane key or [direction, ...children], nested freely.
 *
 * Every flexible child carries `flex: <grow> 1 0`, so a drag is just moving grow between
 * two siblings. That is what makes the arrangement and the sizing independent: any layout
 * is resizable by the same handle code, in whichever direction its container runs. */
const LAYOUTS = {
  cols: { label: "Three columns", spec: ["row", "q", "c", "a"] },
  left2: { label: "Two left, one right", spec: ["row", ["col", "q", "c"], "a"] },
  right2: { label: "One left, two right", spec: ["row", "q", ["col", "c", "a"]] },
  topwide: { label: "One top, two below", spec: ["col", "q", ["row", "c", "a"]] },
  rows: { label: "Three rows", spec: ["col", "q", "c", "a"] },
};
const PANE_IDS = { q: "pane-q", c: "pane-c", a: "pane-a" };
let layoutName = "cols";

const sizeKey = () => `lv.sizes.${layoutName}`;

function readSizes() {
  try {
    const saved = JSON.parse(localStorage.getItem(sizeKey()) || "{}");
    return saved && typeof saved === "object" ? saved : {};
  } catch {
    return {};
  }
}

function writeSize(key, value) {
  const sizes = readSizes();
  sizes[key] = value;
  localStorage.setItem(sizeKey(), JSON.stringify(sizes));
}

function buildLayout(name) {
  layoutName = LAYOUTS[name] ? name : "cols";
  const sizes = readSizes();
  const spec = LAYOUTS[layoutName].spec;

  // Hold the elements before detaching them. getElementById cannot find a node that is no
  // longer in the document, so looking them up after the removal below returns null - the
  // whole script then died on the first pane and the page rendered as bare HTML.
  const panes = Object.fromEntries(
    Object.entries(PANE_IDS).map(([key, id]) => [key, $(id)]),
  );

  const build = (node, path) => {
    if (typeof node === "string") {
      const el = panes[node];
      el.dataset.key = node;
      el.style.flex = `${sizes[node] || 1} 1 0`;
      return el;
    }
    const [dir, ...children] = node;
    const box = document.createElement("div");
    box.className = `box ${dir}`;
    box.dataset.key = path;
    box.style.flex = `${sizes[path] || 1} 1 0`;
    children.forEach((child, i) => {
      if (i) {
        const handle = document.createElement("div");
        handle.className = `split ${dir}`;
        box.append(handle);
      }
      box.append(build(child, `${path}.${i}`));
    });
    return box;
  };

  // Detach the panes first: they are reused across layouts, not rebuilt, so their scroll
  // position and rendered content survive a rearrangement.
  Object.values(panes).forEach((el) => el.remove());
  $("panes").replaceChildren(build(spec, "b"));
  $("panes").querySelectorAll(".split").forEach(wireSplit);
  localStorage.setItem("lv.layout", layoutName);
  const picker = $("set-layout");
  if (picker) picker.value = layoutName;
}

function wireSplit(handle) {
  handle.addEventListener("pointerdown", (e) => {
    const before = handle.previousElementSibling;
    const after = handle.nextElementSibling;
    if (!before || !after) return;
    const vertical = handle.classList.contains("col");
    const rect = (el) => el.getBoundingClientRect();
    const size = (el) => (vertical ? rect(el).height : rect(el).width);

    const startPos = vertical ? e.clientY : e.clientX;
    const a0 = size(before);
    const b0 = size(after);
    const growTotal =
      parseFloat(before.style.flexGrow || 1) + parseFloat(after.style.flexGrow || 1);
    handle.setPointerCapture(e.pointerId);

    const move = (ev) => {
      const delta = (vertical ? ev.clientY : ev.clientX) - startPos;
      const a = Math.max(80, a0 + delta);
      const b = Math.max(80, b0 - delta);
      // Grow is shared between the pair, so their combined share of the parent is
      // unchanged and no other pane moves when these two are resized.
      before.style.flex = `${(a / (a + b)) * growTotal} 1 0`;
      after.style.flex = `${(b / (a + b)) * growTotal} 1 0`;
    };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      writeSize(before.dataset.key, parseFloat(before.style.flexGrow));
      writeSize(after.dataset.key, parseFloat(after.style.flexGrow));
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
  });
}

/* ---------- routing ------------------------------------------------------ */
function show(name) {
  ["problems", "problem", "course", "settings"].forEach((v) => {
    $("view-" + v).hidden = v !== name;
  });
  const nav = ["course", "settings"].includes(name) ? name : "problems";
  document.querySelectorAll("[data-nav]").forEach((a) =>
    a.classList.toggle("active", a.dataset.nav === nav));
}

function route() {
  const hash = location.hash || "#/problems";
  const problem = hash.match(/^#\/p\/(.+)$/);
  if (problem) return openProblem(decodeURIComponent(problem[1]));
  if (hash.startsWith("#/settings")) return show("settings");
  if (hash.startsWith("#/course")) {
    const path = hash.slice("#/course".length).replace(/^\//, "");
    return openCourse(path ? decodeURIComponent(path) : "");
  }
  show("problems");
}

/* ---------- boot --------------------------------------------------------- */
async function main() {
  try {
    // Revalidate every time: sync rewrites this on each run, and a stale catalogue
    // paired with a fresh page is a confusing way to see yesterday's problems.
    DATA = await (await fetch("assets/index.json", { cache: "no-cache" })).json();
  } catch {
    document.body.innerHTML =
      "<p style='padding:24px'>Could not load assets/index.json. Run <code>leetvault site</code>.</p>";
    return;
  }
  DATA.branch = DATA.branch || "main";
  $("repo-title").textContent = DATA.repo || "Problems";
  $("repo-link").textContent = DATA.repo || "";
  $("repo-link").href = `https://github.com/${DATA.repo}`;
  $("view-on-github").href = `https://github.com/${DATA.repo}`;
  $("generated").textContent = DATA.generated_at ? `Updated ${DATA.generated_at}` : "";

  const topics = [...new Set(DATA.problems.flatMap((p) => p.topics || []))].sort();
  $("f-topic").innerHTML += topics.map((t) => `<option>${esc(t)}</option>`).join("");
  const langs = [...new Set(DATA.problems.map((p) => p.lang).filter(Boolean))].sort();
  $("f-lang").innerHTML += langs.map((l) => `<option>${esc(l)}</option>`).join("");

  renderStats();
  applyFilters();

  ["q", "f-topic", "f-diff", "f-lang"].forEach((id) =>
    $(id).addEventListener("input", applyFilters));
  document.querySelectorAll("th[data-sort]").forEach((th) =>
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      sortAsc = key === sortKey ? !sortAsc : true;
      sortKey = key;
      applyFilters();
    }));

  $("open-index").onclick = () => { $("drawer").hidden = false; renderDrawer(); $("drawer-q").focus(); };
  $("close-index").onclick = $("drawer-scrim").onclick = () => { $("drawer").hidden = true; };
  $("drawer-q").addEventListener("input", renderDrawer);
  $("drawer-list").addEventListener("click", () => { $("drawer").hidden = true; });
  $("prev").onclick = () => neighbour(-1);
  $("next").onclick = () => neighbour(1);
  $("btn-history").onclick = openHistory;
  $("m-close").onclick = $("modal-scrim").onclick = () => { $("modal").hidden = true; };
  $("btn-notes").onclick = () => { $("notes-modal").hidden = false; };
  $("n-close").onclick = $("notes-scrim").onclick = () => { $("notes-modal").hidden = true; };

  document.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", () => {
    const src = { q: "q-body", c: "c-body", a: "a-body" }[b.dataset.copy];
    navigator.clipboard.writeText($(src).innerText).then(() => {
      const was = b.textContent; b.textContent = "Copied"; setTimeout(() => (b.textContent = was), 1200);
    });
  }));

  // system -> light -> dark -> system. Resolving "system" to an explicit attribute here
  // keeps the stylesheet down to two palettes instead of three overlapping selectors.
  const THEMES = ["system", "light", "dark"];
  const prefersLight = matchMedia("(prefers-color-scheme: light)");
  const applyTheme = (choice) => {
    const effective = choice === "system" ? (prefersLight.matches ? "light" : "dark") : choice;
    document.documentElement.dataset.theme = effective;
    $("theme-toggle").textContent = { system: "Auto", light: "Light", dark: "Dark" }[choice];
    $("set-theme").value = choice;
    localStorage.setItem("lv.theme", choice);
  };
  let theme = THEMES.includes(localStorage.getItem("lv.theme") || "")
    ? localStorage.getItem("lv.theme")
    : "system";
  applyTheme(theme);
  $("theme-toggle").onclick = () => {
    theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
    applyTheme(theme);
  };
  // Follow the system only while the user has not chosen for themselves.
  prefersLight.addEventListener("change", () => theme === "system" && applyTheme("system"));

  // A template literal: real newlines, no escape sequences to get mangled.
  const SAMPLE = `class Solution:
    def twoSum(self, nums, target):  # a hash map beats sorting
        seen = {}          # index by value
        for i, num in enumerate(nums):
            if target - num in seen:
                return [seen[target - num], i]
            seen[num] = i
        return []`;

  const applyCode = (name) => {
    document.documentElement.dataset.code = name;
    localStorage.setItem("lv.code", name);
    $("set-code").value = name;
    $("code-sample").innerHTML = highlight(SAMPLE, "py");
  };
  applyCode(localStorage.getItem("lv.code") || "github-dark");
  buildLayout(localStorage.getItem("lv.layout") || "cols");
  $("set-layout").onchange = (e) => buildLayout(e.target.value);
  $("set-code").onchange = (e) => applyCode(e.target.value);

  // The rail button and the Settings dropdown are two controls over one preference, so
  // each has to reflect what the other did.
  $("set-theme").onchange = (e) => { theme = e.target.value; applyTheme(theme); };

  // Hiding the rail is a preference, not a per-page state: someone who wants the whole
  // window for three panes wants it on the next problem too.
  const setRail = (hidden) => {
    document.body.classList.toggle("rail-hidden", hidden);
    localStorage.setItem("lv.rail", hidden ? "hidden" : "shown");
  };
  setRail(localStorage.getItem("lv.rail") === "hidden");
  $("rail-toggle").onclick = () => setRail(true);
  $("rail-show").onclick = () => setRail(false);

  addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      $("drawer").hidden = true;
      $("modal").hidden = true;
      $("notes-modal").hidden = true;
    }
    // A single key to reclaim the window, and the same key to get the rail back.
    if (e.key === "\\" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
      setRail(!document.body.classList.contains("rail-hidden"));
    }
  });
  addEventListener("hashchange", route);
  route();
}

main();
