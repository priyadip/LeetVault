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
  $("c-body").textContent = code;
  $("a-body").innerHTML = markdown(analysis) ||
    "<p class='muted'>No analysis yet. Run <code>leetvault sync</code> with AI enabled.</p>";
  $("n-body").innerHTML = markdown(notes) || "<p class='muted'>Empty.</p>";
  $("n-edit").href = ghEdit(`${dir}/notes.md`);
  $("btn-history").textContent = `View history (${(p.history || []).length})`;
  $("btn-history").disabled = !(p.history || []).length;
  restoreSplits();
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
    $("m-code").textContent = await text(versions[n].file);
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

/* ---------- resizable panes --------------------------------------------- */
/* Sizes are per-layout in localStorage: a split you dragged is a preference, and having it
   reset on every navigation would make the feature useless. */
function restoreSplits() {
  const saved = JSON.parse(localStorage.getItem("lv.splits") || "null");
  if (!saved) return;
  ["pane-q", "pane-c", "pane-a"].forEach((id, n) => {
    if (saved[n]) $(id).style.flex = `0 0 ${saved[n]}px`;
  });
}

function saveSplits() {
  localStorage.setItem("lv.splits", JSON.stringify(
    ["pane-q", "pane-c", "pane-a"].map((id) => $(id).getBoundingClientRect().width)));
}

function wireSplit(handle) {
  handle.addEventListener("pointerdown", (e) => {
    const before = handle.previousElementSibling, after = handle.nextElementSibling;
    if (!before || !after) return;
    const vertical = getComputedStyle(handle).cursor === "row-resize";
    const startPos = vertical ? e.clientY : e.clientX;
    const a0 = vertical ? before.getBoundingClientRect().height : before.getBoundingClientRect().width;
    const b0 = vertical ? after.getBoundingClientRect().height : after.getBoundingClientRect().width;
    handle.setPointerCapture(e.pointerId);

    const move = (ev) => {
      const d = (vertical ? ev.clientY : ev.clientX) - startPos;
      const a = Math.max(120, a0 + d), b = Math.max(120, b0 - d);
      before.style.flex = `0 0 ${a}px`;
      after.style.flex = `0 0 ${b}px`;
    };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      if (handle.dataset.split !== "course") saveSplits();
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
  });
}

/* ---------- routing ------------------------------------------------------ */
function show(name) {
  ["problems", "problem", "course"].forEach((v) => { $("view-" + v).hidden = v !== name; });
  const nav = name === "course" ? "course" : "problems";
  document.querySelectorAll("[data-nav]").forEach((a) =>
    a.classList.toggle("active", a.dataset.nav === nav));
}

function route() {
  const hash = location.hash || "#/problems";
  const problem = hash.match(/^#\/p\/(.+)$/);
  if (problem) return openProblem(decodeURIComponent(problem[1]));
  if (hash.startsWith("#/course")) {
    const path = hash.slice("#/course".length).replace(/^\//, "");
    return openCourse(path ? decodeURIComponent(path) : "");
  }
  show("problems");
}

/* ---------- boot --------------------------------------------------------- */
async function main() {
  try {
    DATA = await (await fetch("assets/index.json")).json();
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

  document.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", () => {
    const src = { q: "q-body", c: "c-body", a: "a-body" }[b.dataset.copy];
    navigator.clipboard.writeText($(src).innerText).then(() => {
      const was = b.textContent; b.textContent = "Copied"; setTimeout(() => (b.textContent = was), 1200);
    });
  }));

  document.querySelectorAll(".split").forEach(wireSplit);
  addEventListener("keydown", (e) => {
    if (e.key === "Escape") { $("drawer").hidden = true; $("modal").hidden = true; }
  });
  addEventListener("hashchange", route);
  route();
}

main();
