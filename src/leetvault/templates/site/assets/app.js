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
/* Hand-written for the same reason as the highlighter: no CDN, no build step, still working
 * in five years. The target is not "some Markdown" but a specific one - whatever GitHub
 * renders for the same file. Every problem here is also readable on GitHub, and a reader
 * moving between the two should not meet two different documents. tests/test_site.py pins
 * that claim against GitHub's own renderer on real problem files.
 *
 * Two passes. The inline pass hides code spans, escapes, rebuilt tags and finished links
 * behind sentinels before the emphasis rules run, so an asterisk inside backticks and an
 * underscore inside a URL are never mistaken for markup. The block pass is recursive: a list
 * item's body is parsed as its own document, which is what makes nested lists and
 * multi-paragraph items fall out of the design instead of needing cases of their own. */

/* The tags GitHub keeps. It renders these and silently drops any other well-formed tag,
 * keeping the text inside it - which is why <u> is absent here even though LeetCode writes
 * it: GitHub strips it, so underlining a matched subsequence would be this page showing
 * something the file on GitHub does not.
 *
 * Tags are rebuilt rather than passed through: the name must appear here and every attribute
 * is dropped on the way, so the <th style="border: 1px solid black;"> these files contain
 * still renders, while an onerror= or an href="javascript:" cannot survive a rebuild that
 * emits the name alone. `img` is deliberately absent: images are built from Markdown
 * ![](...) with the source checked by safeUrl, never lifted out of raw HTML. */
const SAFE_TAGS = new Set([
  "details", "summary",
  "table", "thead", "tbody", "tfoot", "caption", "colgroup", "col", "tr", "th", "td",
  "b", "i", "em", "strong", "code", "sub", "sup", "kbd", "s", "strike", "del", "ins",
  "mark", "small", "cite", "abbr", "q", "samp", "var", "tt", "br", "hr",
]);

const FENCE = /^\s{0,3}(`{3,}|~{3,})\s*([A-Za-z0-9+#._-]*)\s*$/;
const ATX = /^\s{0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$/;
const HR = /^\s{0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$/;
// The marker may be the whole line: "-" on its own is an empty list item, not a paragraph.
const LIST = /^(\s*)([-*+]|\d{1,9}[.)])(\s+|$)(.*)$/;
const LIST_START = /^ {0,3}([-*+]|[0-9]{1,9}[.)])( |$)/;
const QUOTE = /^\s{0,3}>\s?/;
const ROW = /^\s*\|.*\|\s*$/;
const DELIM = /^\s*\|[\s:|-]+\|\s*$/;
// A tag, with nothing angled inside it: "x<smi" followed by a distant ">" is not one, and
// GitHub leaves it visible rather than swallowing the text between.
const TAG = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)([^<>]*)>/g;

/* The sentinel is a NUL: no document contains one, and esc() leaves it alone. It is built
 * rather than written so this file stays plain ASCII. */
const MARK = String.fromCharCode(0);
const SENTINEL = new RegExp(MARK + "([0-9]+)" + MARK, "g");

/* Language names as written on a fence, mapped to the extensions the highlighter knows, so a
 * python block inside an analysis is coloured like the submission it discusses. */
const FENCE_LANG = {
  python: "py", python3: "py", py: "py", ruby: "rb", rb: "rb",
  java: "java", kotlin: "kt", kt: "kt", csharp: "cs", "c#": "cs", cs: "cs",
  cpp: "cpp", "c++": "cpp", cxx: "cpp", cc: "cpp", c: "c",
  javascript: "js", js: "js", node: "js", typescript: "ts", ts: "ts",
  go: "go", golang: "go", rust: "rs", rs: "rs",
};

function esc(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/* A link target is allowed when it is plainly external (http, https, mailto), a fragment, or
 * relative - which is to say it names no scheme at all. Everything else is refused and the
 * text left unlinked; javascript: is the reason this function exists. */
function safeUrl(u) {
  return /^(?:https?:\/\/|mailto:|#|[^a-zA-Z]|[^:]*$)/i.test(u) ? u : null;
}

// The href or src of a raw HTML tag, if safeUrl accepts it - quoted either way or bare,
// which is how someone writing one by hand actually writes it.
function attrUrl(attrs) {
  const m = /(?:href|src)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))/i.exec(attrs || "");
  const raw = m ? (m[1] !== undefined ? m[1] : m[2] !== undefined ? m[2] : m[3]) : "";
  return raw && safeUrl(raw) ? esc(raw) : null;
}
function anchor(href, text) {
  return '<a href="' + href + '" target="_blank" rel="noopener">' + text + "</a>";
}

/* Emphasis, kept apart from the rest of the inline pass so link text can be run through it
 * too - GitHub renders [**bold**](url) with the bold intact.
 *
 * This is CommonMark's delimiter-run algorithm rather than a chain of regular expressions.
 * That is not gold-plating: LeetCode's own statements contain overlapping runs, such as
 * "return *the **lexicographically smallest* *subsequence** of*", and a regex chain closes
 * those in the wrong order and emits tags that cross - which no browser renders the way
 * GitHub does. Three rules carry the weight. A run may open only if it is left-flanking and
 * close only if it is right-flanking; an underscore may additionally do neither inside a
 * word, so snake_case survives; and a pair whose lengths sum to a multiple of three is
 * refused unless both lengths are themselves multiples of three. */
const PUNCT = /[!-\/:-@\[-`{-~]/;

/* A delimiter run's two properties, from the characters on either side of it. "Left" means
 * it could begin emphasis, "right" that it could end it - a run is often both, which is
 * exactly why the pairing below needs an algorithm rather than a pattern. */
function flanking(s, start, end) {
  const before = start > 0 ? s[start - 1] : " ";
  const after = end < s.length ? s[end] : " ";
  const beforeSpace = /\s/.test(before);
  const afterSpace = /\s/.test(after);
  // A held fragment - a code span, a link, a rebuilt tag - stands where punctuation
  // stood in the source, and CommonMark decides flanking from that character. Counting
  // the sentinel as punctuation is what lets a `span` followed by *.* emphasise at all.
  const beforePunct = before === MARK || PUNCT.test(before);
  const afterPunct = after === MARK || PUNCT.test(after);
  return {
    left: !afterSpace && (!afterPunct || beforeSpace || beforePunct),
    right: !beforeSpace && (!beforePunct || afterSpace || afterPunct),
    beforePunct,
    afterPunct,
  };
}

function delimiters(s) {
  const nodes = [];
  let text = "";
  let i = 0;
  while (i < s.length) {
    const ch = s[i];
    if (ch !== "*" && ch !== "_" && ch !== "~") { text += ch; i++; continue; }
    let j = i;
    while (j < s.length && s[j] === ch) j++;
    // GFM strikethrough is one or two tildes; a longer run is literal text.
    if (ch === "~" && j - i > 2) { text += s.slice(i, j); i = j; continue; }
    if (text) { nodes.push({ text }); text = ""; }
    const f = flanking(s, i, j);
    nodes.push({
      ch,
      n: j - i,
      size: j - i,
      open: ch === "_" ? f.left && (!f.right || f.beforePunct) : f.left,
      close: ch === "_" ? f.right && (!f.left || f.afterPunct) : f.right,
      dead: false,
      opens: [],
      closes: [],
    });
    i = j;
  }
  if (text) nodes.push({ text });
  return nodes;
}

function emph(s) {
  const nodes = delimiters(s);

  for (let c = 0; c < nodes.length; c++) {
    const closer = nodes[c];
    if (!closer.ch || closer.dead || !closer.close || closer.n === 0) continue;

    let o = -1;
    for (let k = c - 1; k >= 0; k--) {
      const cand = nodes[k];
      if (!cand.ch || cand.dead || cand.n === 0) continue;
      if (cand.ch !== closer.ch || !cand.open) continue;
      // The rule of three, which is what keeps "***x***" and its malformed cousins nesting
      // the way GitHub nests them.
      const both = (closer.open && closer.close) || (cand.open && cand.close);
      if (both && (cand.size + closer.size) % 3 === 0 &&
          !(cand.size % 3 === 0 && closer.size % 3 === 0)) continue;
      o = k;
      break;
    }
    if (o === -1) {
      if (!closer.open) closer.dead = true;
      continue;
    }

    const opener = nodes[o];
    const strong = closer.ch !== "~" && opener.n >= 2 && closer.n >= 2;
    const used = closer.ch === "~" ? Math.min(opener.n, closer.n) : strong ? 2 : 1;
    const tag = closer.ch === "~" ? "del" : strong ? "strong" : "em";
    opener.n -= used;
    closer.n -= used;
    // Matches are found innermost first, so the opener's tags accumulate outermost-first and
    // the closer's innermost-first; emitting each list in order then nests them correctly.
    opener.opens.unshift(tag);
    closer.closes.push(tag);
    // Delimiters skipped over can never pair with anything now.
    for (let k = o + 1; k < c; k++) if (nodes[k].ch) nodes[k].dead = true;
    if (closer.n > 0) c--;
  }

  let out = "";
  for (const node of nodes) {
    if (!node.ch) { out += node.text; continue; }
    out += node.closes.map((t) => "</" + t + ">").join("");
    out += node.ch.repeat(node.n);
    out += node.opens.map((t) => "<" + t + ">").join("");
  }
  return out;
}

function inline(s) {
  const held = [];
  const hold = (html) => MARK + (held.push(html) - 1) + MARK;

  // Code spans and backslash escapes leave the text before anything else and return at the
  // very end, so markup written inside them is shown rather than applied - which is what
  // GitHub does for `<u>a</u>`, and the reason several problems can describe a subsequence
  // at all.
  let t = String(s)
    // A line ending inside a code span is a space, not a break. GFM says so, and a statement
    // that writes its mapping across two lines depends on it.
    .replace(/(`+)([\s\S]*?)\1/g, (_, __, code) =>
      hold("<code>" + esc(code.replace(/\n/g, " ")) + "</code>"))
    .replace(/\\([\\`*_{}[\]()#+\-.!|~>])/g, (_, ch) => hold(esc(ch)))
    // Two trailing spaces, or a backslash, before a line ending is a hard break; every other
    // line ending inside a paragraph is just a space.
    .replace(/(?: {2,}|\\)\n/g, () => hold("<br>"))
    .replace(/\n/g, " ");

  // Tags are settled here, on the raw text, where a "<" is still a "<". Keeping one means
  // holding it: esc() below must not reach what has just been rebuilt.
  let anchors = 0;
  t = t.replace(TAG, (_, slash, name, attrs) => {
    const tag = name.toLowerCase();
    if (tag !== "a" && tag !== "img") {
      return SAFE_TAGS.has(tag) ? hold("<" + slash + tag + ">") : "";
    }
    // These two are the exception to dropping every attribute, because for them the
    // attribute is the content: an anchor without its href and an image without its src are
    // not the same document. Exactly one attribute survives on each, and only the one
    // safeUrl accepts - a closing </a> is kept only where an opening tag was.
    if (tag === "a" && slash) {
      if (!anchors) return "";
      anchors -= 1;
      return hold("</a>");
    }
    const url = attrUrl(attrs);
    if (!url) return "";
    if (tag === "img") return hold('<img src="' + url + '" alt="" loading="lazy">');
    anchors += 1;
    return hold('<a href="' + url + '" target="_blank" rel="noopener">');
  });

  t = esc(t)
    // An entity the author wrote stays an entity: esc() has just turned its ampersand into
    // &amp;, which would otherwise show the reader &lt; where GitHub shows <.
    .replace(/&amp;(#[0-9]+|#x[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]{1,31});/g, "&$1;");

  // Images before links - the two syntaxes differ by a leading "!", so the link rule would
  // otherwise claim the bracket pair and leave a stray "!" in front of an anchor. All three
  // results are held, because a URL must not reach the emphasis rules: the underscores in
  // one would come back as <em>.
  t = t
    .replace(/!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+[^)]*)?\)/g, (m, alt, src) => {
      const url = safeUrl(src);
      return url ? hold('<img src="' + url + '" alt="' + alt + '" loading="lazy">') : m;
    })
    .replace(/\[([^\]]+)\]\(\s*([^)\s]*)(?:\s+[^)]*)?\)/g, (m, text, href) => {
      const url = safeUrl(href);
      return url ? hold(anchor(url, emph(text))) : m;
    })
    // Bare URLs are links on GitHub. Trailing sentence punctuation is left outside, so a URL
    // that ends a sentence does not swallow the full stop.
    .replace(/(^|[\s(])(https?:\/\/[^\s<>()]*[^\s<>().,;:!?])/g, (_, pre, url) =>
      pre + hold(anchor(url, url)));

  t = emph(t);

  // Held fragments can contain sentinels of their own - a code span inside a link - so this
  // runs until none are left rather than once. Indices only point backwards, so it ends.
  for (let pass = 0; pass < 8 && t.indexOf(MARK) !== -1; pass++) {
    t = t.replace(SENTINEL, (_, n) => held[n]);
  }
  return t;
}

function codeBlock(code, lang) {
  const ext = FENCE_LANG[(lang || "").toLowerCase()];
  return '<pre><code class="code">' + (ext ? highlight(code, ext) : esc(code)) + "</code></pre>";
}

// Splits one table row, honouring an escaped pipe inside a cell - the only way a pipe can
// appear in a table without ending the cell.
function cells(row) {
  const s = row.trim().replace(/^\|/, "").replace(/\|$/, "");
  const parts = [];
  let cur = "";
  for (let k = 0; k < s.length; k++) {
    if (s[k] === "\\" && s[k + 1] === "|") { cur += "|"; k++; }
    else if (s[k] === "|") { parts.push(cur); cur = ""; }
    else cur += s[k];
  }
  parts.push(cur);
  return parts.map((c) => c.trim());
}

// A GFM table runs to the first blank line or the start of another block - anything else,
// even a line with no pipes in it, is one more row.
function startsBlock(l) {
  return !l.trim() || ATX.test(l) || FENCE.test(l) || HR.test(l) || QUOTE.test(l) ||
    LIST_START.test(l) || /^\s{0,3}<\/?[a-zA-Z]/.test(l);
}

function markdown(src) {
  return blocks((src || "").replace(/\r\n?/g, "\n").split("\n"));
}

/* `tight` is set for the items of a tight list, where GitHub renders an item's paragraphs
 * without their <p> wrapper. It is decided once for the whole list, so its items are spaced
 * evenly, and it does not reach a nested list - that one decides for itself. */
function blocks(lines, tight) {
  const out = [];
  let para = [];
  let i = 0;

  const flush = () => {
    if (!para.length) return;
    // Leading indentation is not content, but trailing spaces are - two of them are a hard
    // break. The paragraph goes through the inline pass whole rather than line by line, so a
    // code span or a link may run across a line ending, as they do on GitHub.
    const html = inline(para.map((l) => l.replace(/^ +/, "")).join("\n"));
    out.push(tight ? html : "<p>" + html + "</p>");
    para = [];
  };

  while (i < lines.length) {
    const line = lines[i];

    const fence = line.match(FENCE);
    if (fence) {
      flush();
      const close = new RegExp("^\\s{0,3}" + fence[1][0] + "{" + fence[1].length + ",}\\s*$");
      const body = [];
      i++;
      while (i < lines.length && !close.test(lines[i])) body.push(lines[i++]);
      i++;
      out.push(codeBlock(body.join("\n"), fence[2]));
      continue;
    }

    // Four spaces is a code block only where no paragraph is open; indented text under one is
    // a continuation of it. List items never reach here - their bodies are parsed separately,
    // with the item's indentation already removed.
    if (!para.length && line.trim() && /^ {4}\S/.test(line)) {
      const body = [];
      while (i < lines.length && (/^ {4}/.test(lines[i]) ||
             (!lines[i].trim() && /^ {4}\S/.test(lines[i + 1] || "")))) {
        body.push(lines[i++].replace(/^ {4}/, ""));
      }
      out.push(codeBlock(body.join("\n"), ""));
      continue;
    }

    // Setext headings, before the horizontal rule: a row of dashes under a paragraph
    // underlines it, while the same row after a blank line is a rule.
    if (para.length && /^\s{0,3}=+\s*$/.test(line)) {
      const text = para.join(" ").trim();
      para = [];
      i++;
      out.push("<h1>" + inline(text) + "</h1>");
      continue;
    }
    if (para.length && /^\s{0,3}-+\s*$/.test(line)) {
      const text = para.join(" ").trim();
      para = [];
      i++;
      out.push("<h2>" + inline(text) + "</h2>");
      continue;
    }

    const heading = line.match(ATX);
    if (heading) {
      flush();
      const n = heading[1].length;
      out.push("<h" + n + ">" + inline(heading[2]) + "</h" + n + ">");
      i++;
      continue;
    }

    if (HR.test(line)) { flush(); out.push("<hr>"); i++; continue; }

    // Raw HTML. Hints arrive as <details>/<summary>, which stay one line each so the Markdown
    // between them is still parsed - that is how GitHub renders them, and it is what makes a
    // hint body readable. A <table> is taken whole, since its content is HTML.
    const name = (line.match(/^\s*<(\/?[a-zA-Z][a-zA-Z0-9]*)/) || [])[1];
    const opener = (name || "").toLowerCase();
    if (opener === "table") {
      flush();
      const block = [];
      while (i < lines.length && !/<\/table\s*>/i.test(lines[i])) block.push(lines[i++]);
      if (i < lines.length) block.push(lines[i++]);
      out.push(inline(block.join("\n")));
      continue;
    }
    if (opener === "details" || opener === "/details" || opener === "summary") {
      flush();
      out.push(inline(line.trim()));
      i++;
      continue;
    }

    const delim = DELIM.test(lines[i + 1] || "") ? cells(lines[i + 1]) : null;
    if (ROW.test(line) && delim && delim.length === cells(line).length) {
      flush();
      const head = cells(line);
      const align = delim.map((c) =>
        /^:-+:$/.test(c) ? "center" : /^-+:$/.test(c) ? "right" : /^:-+$/.test(c) ? "left" : "");
      const cell = (tag, text, n) =>
        "<" + tag + (align[n] ? ' style="text-align:' + align[n] + '"' : "") + ">" +
        inline(text || "") + "</" + tag + ">";
      i += 2;
      const rows = [];
      while (i < lines.length && !startsBlock(lines[i])) rows.push(cells(lines[i++]));
      // Every row is padded or truncated to the header's width, which is what GitHub does
      // with a trailing line that was never meant to be a row at all.
      out.push("<table><thead><tr>" + head.map((h, n) => cell("th", h, n)).join("") +
        "</tr></thead><tbody>" +
        rows.map((r) => "<tr>" + head.map((_, n) => cell("td", r[n], n)).join("") + "</tr>")
          .join("") +
        "</tbody></table>");
      continue;
    }

    if (QUOTE.test(line)) {
      flush();
      const quote = [];
      while (i < lines.length && QUOTE.test(lines[i])) quote.push(lines[i++].replace(QUOTE, ""));
      out.push("<blockquote>" + blocks(quote) + "</blockquote>");
      continue;
    }

    const item = line.match(LIST);
    if (item && item[1].length <= 3) {
      flush();
      const indent = item[1].length;
      const ordered = /[0-9]/.test(item[2]);
      const start = ordered ? parseInt(item[2], 10) : 1;
      const items = [];
      let loose = false;

      while (i < lines.length) {
        // Blank lines between items belong to the list, and their presence is what makes it
        // loose; the item after them is still part of it.
        let j = i;
        while (j < lines.length && !lines[j].trim()) j++;
        const m = j < lines.length ? lines[j].match(LIST) : null;
        if (!m || m[1].length !== indent || /[0-9]/.test(m[2]) !== ordered) break;
        if (j > i) loose = true;
        i = j;

        const col = m[1].length + m[2].length + (m[3].length || 1);
        const body = [m[4]];
        i++;

        while (i < lines.length) {
          const l = lines[i];
          if (!l.trim()) {
            // A blank run keeps the item only if content indented to its column follows;
            // otherwise it is left for the loop above to judge.
            let k = i;
            while (k < lines.length && !lines[k].trim()) k++;
            if (k >= lines.length || lines[k].slice(0, col).trim() !== "") break;
            loose = true;
            while (i < k) { body.push(""); i++; }
            continue;
          }
          if (l.slice(0, col).trim() === "") { body.push(l.slice(col)); i++; continue; }
          // A line that is neither indented to the content column nor the start of another
          // block is a lazy continuation of the item's paragraph - how a long constraint
          // wraps in these files.
          if (!startsBlock(l) && !ROW.test(l) && body.length && body[body.length - 1].trim()) {
            body.push(l.replace(/^ +/, ''));
            i++;
            continue;
          }
          break;
        }
        items.push(body);
      }

      const tag = ordered ? "ol" : "ul";
      const attr = ordered && start !== 1 ? ' start="' + start + '"' : "";
      out.push("<" + tag + attr + ">" +
        items.map((body) => "<li>" + blocks(body, !loose) + "</li>").join("") +
        "</" + tag + ">");
      continue;
    }

    if (!line.trim()) { flush(); i++; continue; }

    para.push(line);
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
