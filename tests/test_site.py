from __future__ import annotations

import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest
from rich.console import Console

from leetvault.config import ConfigStore
from leetvault.site import (
    INDEX_JSON,
    NOJEKYLL,
    SITE_FILES,
    build_index,
    refresh_index,
    run_site,
    write_site,
)


def _problem(repo: Path, slug: str, fid: int, *, analysis=True, history=(), topics="Array") -> None:
    d = repo / "Problems" / slug
    d.mkdir(parents=True)
    (d / "metadata.json").write_text(
        json.dumps(
            {
                "frontend_id": fid,
                "question_id": fid,
                "title": slug.replace("-", " ").title(),
                "title_slug": slug,
                "difficulty": "Easy",
                "lang": "python3",
                "url": f"https://leetcode.com/problems/{slug}/",
                "timestamp": 1_760_000_000,
            }
        ),
        encoding="utf-8",
    )
    (d / "latest.py").write_text("class Solution: ...", encoding="utf-8")
    (d / "question.md").write_text(
        f"# {fid}. Title\n\n**Difficulty:** Easy\n**Topics:** {topics}\n", encoding="utf-8"
    )
    if analysis:
        (d / "analysis.md").write_text("## Approach\nHash map.", encoding="utf-8")
    for sid in history:
        (d / "history").mkdir(exist_ok=True)
        (d / "history" / f"submission_{sid}.py").write_text("old", encoding="utf-8")


def test_index_catalogues_the_repository(tmp_path: Path) -> None:
    _problem(tmp_path, "two-sum", 1, history=(100, 300, 200))
    _problem(tmp_path, "add-two-numbers", 2, analysis=False, topics="Math, Linked List")

    index = build_index(tmp_path, "owner/repo")
    assert [p["id"] for p in index["problems"]] == [1, 2]
    first, second = index["problems"]
    assert first["slug"] == "two-sum"
    assert first["ext"] == "py"
    assert first["date"] == "2025-10-09"
    assert first["has_analysis"] is True
    assert second["has_analysis"] is False


def test_topics_come_from_question_md_not_the_database(tmp_path: Path) -> None:
    """metadata.json has no topics field. Reading them from question.md is what lets the
    site be built from a checkout alone, including on a runner with no database."""
    _problem(tmp_path, "two-sum", 1, topics="Array, Hash Table")
    problem = build_index(tmp_path, "owner/repo")["problems"][0]
    assert problem["topics"] == ["Array", "Hash Table"]


def test_history_is_newest_first(tmp_path: Path) -> None:
    """Submission ids are monotonic, and the latest attempt is the one a reader wants."""
    _problem(tmp_path, "two-sum", 1, history=(100, 300, 200))
    history = build_index(tmp_path, "owner/repo")["problems"][0]["history"]
    assert [h["id"] for h in history] == [300, 200, 100]


def test_course_tree_mirrors_the_folder_layout(tmp_path: Path) -> None:
    """The hierarchy is the directory structure, so reorganising is a file move rather
    than an edit to some manifest that could fall out of step."""
    course = tmp_path / "Course" / "Machine Learning" / "Foundations"
    course.mkdir(parents=True)
    (course / "1.1 Linear Algebra.md").write_text("# Linear Algebra", encoding="utf-8")
    (tmp_path / "Course" / "Reading.md").write_text("# Reading", encoding="utf-8")

    tree = build_index(tmp_path, "owner/repo")["course"]
    titles = [n["title"] for n in tree]
    assert "Machine Learning" in titles
    ml = next(n for n in tree if n["title"] == "Machine Learning")
    leaf = ml["children"][0]["children"][0]
    assert leaf["title"] == "1.1 Linear Algebra"
    assert leaf["path"] == "Course/Machine Learning/Foundations/1.1 Linear Algebra.md"


def test_write_site_lays_the_page_at_the_repo_root(tmp_path: Path) -> None:
    """Pages serving from /docs would only publish that folder, so every problem would have
    to be copied into a second tree and kept in step forever."""
    _problem(tmp_path, "two-sum", 1)
    write_site(tmp_path, "owner/repo")
    for name in SITE_FILES:
        assert (tmp_path / name).is_file(), name
    assert (tmp_path / NOJEKYLL).is_file(), "Jekyll would reinterpret the tree"
    assert json.loads((tmp_path / INDEX_JSON).read_text(encoding="utf-8"))["problems"]


def test_refresh_index_does_not_install_a_site(tmp_path: Path) -> None:
    """sync calls this. A repository without a site should not grow one because a sync ran."""
    _problem(tmp_path, "two-sum", 1)
    assert refresh_index(tmp_path, "owner/repo") is False
    assert not (tmp_path / INDEX_JSON).exists()

    write_site(tmp_path, "owner/repo")
    _problem(tmp_path, "add-two-numbers", 2)
    assert refresh_index(tmp_path, "owner/repo") is True
    index = json.loads((tmp_path / INDEX_JSON).read_text(encoding="utf-8"))
    assert len(index["problems"]) == 2


def test_site_without_publish_touches_nothing_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import leetvault.bot as bot

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("must not reach GitHub without --publish")

    monkeypatch.setattr(bot, "_run_gh", explode)
    _problem(tmp_path, "two-sum", 1)
    console = Console(record=True, width=200)
    run_site(console, repo=tmp_path, publish=False)
    assert (tmp_path / "index.html").is_file()
    assert "1 problem(s)" in console.export_text()


def test_publish_reports_each_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import leetvault.bot as bot
    import leetvault.site as site

    ConfigStore().set("repo_url", "https://github.com/owner/repo.git")
    _problem(tmp_path, "two-sum", 1)
    monkeypatch.setattr(bot, "_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(bot, "_commit_and_push", lambda *a, **k: bot.Step("commit and push", True))
    monkeypatch.setattr(site, "_enable_pages", lambda slug, branch: site.Step("Pages", True))

    console = Console(record=True, width=200)
    run_site(console, repo=tmp_path, publish=True)
    output = console.export_text()
    assert "OK" in output
    assert "github.io/repo" in output, "the user needs the URL the site will appear at"


# --- the page itself -------------------------------------------------------------------


def _node() -> str | None:
    node = shutil.which("node")
    if node is None:
        return None
    try:
        if subprocess.run([node, "-e", ""], capture_output=True, timeout=30).returncode:
            return None
    except OSError:
        return None
    return node


def _asset(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "src/leetvault/templates/site" / name


def test_page_javascript_parses() -> None:
    """A syntax error here is a blank page for everyone who visits, and nothing in the
    Python suite would notice."""
    node = _node()
    if node is None:
        pytest.skip("node is not available")
    result = subprocess.run(
        [node, "--check", str(_asset("assets/app.js"))], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_markdown_renderer_handles_what_these_files_contain() -> None:
    """The renderer is hand-written to avoid a CDN dependency, which puts the burden of
    correctness here. Analysis files are full of tables, fences and lists."""
    node = _node()
    if node is None:
        pytest.skip("node is not available")

    script = """
    import { readFileSync } from "node:fs";
    const src = readFileSync(process.env.APP_JS, "utf8");
    const mod = src.slice(src.indexOf("/* ---------- Markdown"),
      src.indexOf("/* ---------- fetching"))
      + "\\nexport { markdown };";
    const { markdown } = await import("data:text/javascript," + encodeURIComponent(mod));
    const html = markdown([
      "## Complexity", "", "```python", "x = 1  # a < b", "```", "",
      "| Step | Action |", "|---|---|", "| 1 | store `2` |", "",
      "- bulleted", "1. numbered", "", "> quoted",
    ].join("\\n"));
    const hostile = markdown("<img src=x onerror=alert(1)>");
    const checks = {
      heading: /<h2>Complexity<\\/h2>/.test(html),
      fence: /<pre><code class="code">/.test(html) && /<[/]code><[/]pre>/.test(html)
        && /class="t-com"># a &lt; b<[/]span>/.test(html),
      table: /<th>Step<\\/th>/.test(html) && /<td>store <code>2<\\/code><\\/td>/.test(html),
      bullets: /<ul><li>bulleted<\\/li><\\/ul>/.test(html),
      numbered: /<ol><li>numbered<\\/li><\\/ol>/.test(html),
      quote: /<blockquote>/.test(html),
      srcKeptHandlerDropped: /<img src="x"/.test(hostile) && !/onerror/i.test(hostile),
    };
    const bad = Object.entries(checks).filter(([, v]) => !v).map(([k]) => k);
    if (bad.length) { console.error("failed: " + bad.join(", ") + "\\n" + html); process.exit(1); }
    """
    import os

    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "APP_JS": str(_asset("assets/app.js"))},
    )
    assert result.returncode == 0, result.stderr


def test_page_never_writes_repo_content_into_html_unescaped() -> None:
    """analysis.md is model-generated and notes.md is free-form, so both are untrusted for
    this purpose even though they are the user's own repository."""
    app = _asset("assets/app.js").read_text(encoding="utf-8")
    assert "function esc(" in app
    # The two places repo text becomes markup both go through the escaping path.
    assert "esc(p.title)" in app
    assert "replace(/[&<>\"']/g" in app


def test_publish_stages_the_site_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The commit helper defaults to staging .github for the Q&A bot. Called without the
    site's own paths it committed nothing, the publish still reported OK, and GitHub Pages
    quietly served the rendered README instead of the page."""
    import leetvault.bot as bot
    import leetvault.site as site

    ConfigStore().set("repo_url", "https://github.com/owner/repo.git")
    _problem(tmp_path, "two-sum", 1)
    captured: dict[str, object] = {}

    def fake_push(repo_path, branch="main", paths=(".github",), message="") -> bot.Step:  # type: ignore[no-untyped-def]
        captured["paths"] = paths
        return bot.Step("commit and push", True)

    monkeypatch.setattr(bot, "_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(bot, "_commit_and_push", fake_push)
    monkeypatch.setattr(site, "_enable_pages", lambda slug, branch: site.Step("Pages", True))

    run_site(Console(record=True, width=200), repo=tmp_path, publish=True)

    staged = set(captured["paths"])  # type: ignore[arg-type]
    assert "index.html" in staged
    assert "assets" in staged
    assert NOJEKYLL in staged
    assert ".github" not in staged, "publishing a site must not sweep in the bot's files"


def test_every_generated_file_is_covered_by_the_staged_paths(tmp_path: Path) -> None:
    """A file written but never staged is a file the site silently lacks."""
    from leetvault.site import SITE_PATHS

    _problem(tmp_path, "two-sum", 1)
    for written in write_site(tmp_path, "owner/repo"):
        rel = written.relative_to(tmp_path).as_posix()
        assert any(rel == p or rel.startswith(f"{p}/") for p in SITE_PATHS), rel


def test_only_one_thing_scrolls() -> None:
    """Two scrollbars for one list is the symptom of the shell growing past the viewport as
    well as the region that owns the content. The shell is fixed to the viewport instead."""
    css = _asset("assets/style.css").read_text(encoding="utf-8")
    assert "html,body{height:100%}" in css
    body = css.split("body{margin:0")[1].split("}")[0]
    assert "overflow:hidden" in body, "the page itself must never scroll"
    assert "#main{" in css and "overflow:hidden" in css.split("#main{")[1].split("}")[0]
    # The table is the thing that scrolls, and needs min-height:0 to be allowed to.
    wrap = css.split(".table-wrap{")[1].split("}")[0]
    assert "overflow:auto" in wrap and "min-height:0" in wrap


def test_the_sidebar_can_be_hidden_for_a_full_window() -> None:
    """Three panes on a problem view want the whole width."""
    html = _asset("index.html").read_text(encoding="utf-8")
    css = _asset("assets/style.css").read_text(encoding="utf-8")
    app = _asset("assets/app.js").read_text(encoding="utf-8")

    assert 'id="rail-toggle"' in html, "no way to collapse it"
    assert 'id="rail-show"' in html, "no way to get it back"
    assert "body.rail-hidden #rail{display:none}" in css
    assert "body.rail-hidden #rail-show{display:block}" in css
    # The inset for the floating button belongs on the header. Putting it on the view
    # held the panes 56px off the left edge for a button that sits above them.
    assert "body.rail-hidden .page-head{padding-left:44px}" in css
    assert "body.rail-hidden section{padding-left" not in css
    assert 'localStorage.setItem("lv.rail"' in app, "the choice must survive navigation"


def test_theme_can_be_switched_and_defaults_to_the_system() -> None:
    """Three states, not two: someone who has not chosen should follow their system, and a
    choice must win over it in both directions - including light on a dark machine."""
    css = _asset("assets/style.css").read_text(encoding="utf-8")
    html = _asset("index.html").read_text(encoding="utf-8")
    app = _asset("assets/app.js").read_text(encoding="utf-8")

    assert 'id="theme-toggle"' in html
    assert ':root[data-theme="light"]{' in css, "an explicit light choice must win"
    assert ":root:not([data-theme]){" in css, "unchosen must follow the system"
    assert '"system", "light", "dark"' in app
    assert 'localStorage.setItem("lv.theme"' in app, "the choice must survive a reload"
    # Following the system after an explicit choice would ignore the user.
    assert 'theme === "system" && applyTheme("system")' in app


def test_the_page_still_themes_itself_without_javascript() -> None:
    """The media query is the fallback if the script never runs - a page that renders black
    text on a black ground because one file 404'd is worse than one that ignores a toggle."""
    css = _asset("assets/style.css").read_text(encoding="utf-8")
    assert "@media (prefers-color-scheme: light)" in css


def test_a_hidden_view_is_actually_hidden() -> None:
    """`section{display:flex}` is more specific than the hidden attribute's own
    display:none, so hiding a view did nothing: every screen stacked onto one page and the
    problem panes were left with a third of the window."""
    css = _asset("assets/style.css").read_text(encoding="utf-8")
    assert "[hidden]{display:none !important}" in css

    # The rule has to come before the one that beat it, and stay stronger than it.
    assert css.index("[hidden]{") < css.index("section{padding")
    app = _asset("assets/app.js").read_text(encoding="utf-8")
    assert '$("view-" + v).hidden = v !== name' in app, "views are toggled by the attribute"


def test_the_panes_can_use_the_whole_window() -> None:
    """A fixed floor would clip on a short window, which is worse than short panes."""
    css = _asset("assets/style.css").read_text(encoding="utf-8")
    panes = css.split("#panes{")[1].split("}")[0]
    assert "flex:1 1 auto" in panes
    assert "min-height:0" in panes, "a floor here clips instead of shrinking"


def test_panes_are_sized_by_proportion_not_pixels() -> None:
    """Pixel widths saved at one window size cannot fill another: a layout dragged narrow
    left a band of dead space when the window grew. Every flexible child carries a grow
    value instead, so it fills whatever it is given."""
    app = _asset("assets/app.js").read_text(encoding="utf-8")
    assert "${sizes[node] || 1} 1 0" in app
    drag = app.split("const move = (ev)")[1].split("};")[0]
    assert "1 0`" in drag and "px" not in drag, "a drag must set grow, not a pixel width"


def test_resizing_a_pair_leaves_every_other_pane_alone() -> None:
    """Grow is moved between the two panes either side of the handle, so their combined
    share of the parent is unchanged and nothing else on screen shifts."""
    app = _asset("assets/app.js").read_text(encoding="utf-8")
    assert "growTotal" in app
    assert "* growTotal" in app


def test_any_arrangement_is_built_from_one_spec() -> None:
    """ "Two stacked left, one down the right" is a different tree over the same three
    elements, not a second copy of the markup."""
    app = _asset("assets/app.js").read_text(encoding="utf-8")
    assert 'left2: { label: "Two left, one right", spec: ["row", ["col", "q", "c"], "a"] }' in app
    assert 'rows: { label: "Three rows", spec: ["col", "q", "c", "a"] }' in app
    # The panes are moved, never rebuilt, so their scroll position and content survive.
    assert "Object.values(panes).forEach((el) => el.remove());" in app
    assert 'localStorage.setItem("lv.layout"' in app


def test_each_layout_remembers_its_own_sizes() -> None:
    """Sizes that made sense as three columns are meaningless as three rows."""
    app = _asset("assets/app.js").read_text(encoding="utf-8")
    assert "const sizeKey = () => `lv.sizes.${layoutName}`;" in app


def test_a_corrupt_saved_size_does_not_break_the_layout() -> None:
    app = _asset("assets/app.js").read_text(encoding="utf-8")
    read = app.split("function readSizes(")[1].split(chr(10) + "}")[0]
    assert "try {" in read and "catch" in read
    assert "|| 1" in app, "a missing size falls back to an equal share"


def test_the_problem_page_is_only_question_code_and_analysis() -> None:
    """A permanent notes band under the panes is height taken from all three for something
    usually collapsed. It opens as a modal instead."""
    html = _asset("index.html").read_text(encoding="utf-8")
    app = _asset("assets/app.js").read_text(encoding="utf-8")

    problem = html.split('<section id="view-problem"')[1].split("</section>")[0]
    assert 'id="panes"' in problem
    assert 'class="notes"' not in problem, "notes must not sit in the page flow"
    assert 'id="btn-notes"' in problem, "but it still has to be reachable"

    assert 'id="notes-modal"' in html
    assert '$("btn-notes").onclick' in app
    # Escape closes every overlay, including this one.
    escape = app.split('if (e.key === "Escape")')[1].split("}")[0]
    assert "notes-modal" in escape


def test_hints_render_as_collapsible_details() -> None:
    """LeetCode writes hints as <details>/<summary> and GitHub renders them natively, so
    escaping every tag showed the reader raw markup on the 87 problems that have hints.
    GitHub keeps the tag and drops the attribute, and so does this - a rebuild that emits the
    name alone is what makes onclick= and onerror= unable to survive."""
    node = _node()
    if node is None:
        pytest.skip("node is not available")

    script = r"""
    import { readFileSync } from "node:fs";
    const src = readFileSync(process.env.APP_JS, "utf8");
    const mod = src.slice(src.indexOf("/* ---------- Markdown"),
      src.indexOf("/* ---------- fetching"))
      + "\nexport { markdown };";
    const { markdown } = await import("data:text/javascript," + encodeURIComponent(mod));

    const html = markdown("<details>\n<summary>Hint 1</summary>\n\nUse a set.\n\n</details>");
    const hostile = markdown(
      "<details onclick=alert(1)>\n<img src=x onerror=alert(2)>\n<script>x</script>");
    const checks = {
      details: /<details>/.test(html) && /<\/details>/.test(html),
      summary: /<summary>Hint 1<\/summary>/.test(html),
      body: /Use a set\./.test(html),
      noAttributes: !/<details[^>]/.test(hostile) && !/<summary[^>]/.test(hostile),
      attributeDropped: /<details>/.test(hostile) && !/onclick/.test(hostile),
      scriptDropped: !/<script/i.test(hostile) && !/onerror|onclick/i.test(hostile),
    };
    const bad = Object.entries(checks).filter(([, v]) => !v).map(([k]) => k);
    if (bad.length) { console.error("failed: " + bad.join(", ") + "\n" + html + "\n" + hostile);
      process.exit(1); }
    """
    import os

    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "APP_JS": str(_asset("assets/app.js"))},
    )
    assert result.returncode == 0, result.stderr


def test_the_page_boots_and_renders_a_view() -> None:
    """A script that throws leaves the static shell on screen - sidebar, no content - which
    is how a detached-element bug shipped looking like a styling problem.

    The fixture's DOM stub is deliberately strict: getElementById returns an element only
    while it is attached. An earlier, lenient stub handed back a fresh object for any id and
    so cheerfully "found" nodes the code had just detached, missing the bug entirely.
    """
    node = _node()
    if node is None:
        pytest.skip("node is not available")

    import os

    fixture = Path(__file__).resolve().parent / "fixtures" / "boot_page.mjs"
    for hash_ in ("#/problems", "#/p/two-sum", "#/course", "#/settings"):
        result = subprocess.run(
            [node, str(fixture)],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "APP_JS": str(_asset("assets/app.js")), "BOOT_HASH": hash_},
        )
        assert result.returncode == 0, f"{hash_}: {result.stderr[:400]}"


def test_assets_are_versioned_so_a_publish_is_not_served_from_cache() -> None:
    """GitHub Pages sends max-age=600. Without a version in the URL a visitor keeps running
    the previous script for ten minutes after an update - which is indistinguishable from
    the update not working, and cost a round trip of "still broken" when it was not."""
    from leetvault.site import asset_version

    version = asset_version(_asset(""))
    assert len(version) == 12

    written = _asset("index.html").read_text(encoding="utf-8")
    assert "__ASSET_VERSION__" in written, "the template carries the placeholder"


def test_the_written_page_has_a_real_version_not_the_placeholder(tmp_path: Path) -> None:
    from leetvault.site import asset_version, write_site

    _problem(tmp_path, "two-sum", 1)
    write_site(tmp_path, "owner/repo")
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    version = asset_version(_asset(""))

    assert "__ASSET_VERSION__" not in html, "the placeholder must be substituted"
    assert f"assets/app.js?v={version}" in html
    assert f"assets/style.css?v={version}" in html


def test_the_version_changes_when_the_page_changes(tmp_path: Path) -> None:
    """A digest of the page's own code: same code, same URL; changed code, new URL."""
    import shutil

    from leetvault.site import asset_version

    fake = tmp_path / "templates"
    (fake / "assets").mkdir(parents=True)
    for name in ("index.html", "assets/app.js", "assets/style.css"):
        shutil.copyfile(_asset(name), fake / name)

    before = asset_version(fake)
    assert asset_version(fake) == before, "unchanged input must give the same version"
    (fake / "assets/app.js").write_text("// different", encoding="utf-8")
    assert asset_version(fake) != before


def test_the_catalogue_is_never_served_from_cache() -> None:
    """sync rewrites index.json on every run; a stale one paired with a fresh page shows
    yesterday's problems."""
    app = _asset("assets/app.js").read_text(encoding="utf-8")
    assert 'fetch("assets/index.json", { cache: "no-cache" })' in app


def test_the_problem_view_reaches_the_window_edges() -> None:
    """Panes are the whole point of that screen; a wide margin around them is window given
    to nothing. The header keeps the inset the floating sidebar button needs."""
    css = _asset("assets/style.css").read_text(encoding="utf-8")
    assert "#view-problem{padding:8px;gap:8px}" in css
    section = css.split("section{padding:")[1].split(";")[0]
    assert section == "10px 12px", f"generic section padding drifted to {section}"


# Ignored on both sides of the comparison below: GitHub wraps every heading in a permalink
# anchor and decorates its output with attributes the reader never sees. `tbody` is ignored
# for a different reason - every HTML parser inserts one into a table that omits it, so
# whether the string carries it is not something a reader can perceive. `thead` is not in
# this set, because no parser inserts that one.
_SKIP_TAGS = {"a", "article", "svg", "path", "g", "div", "span", "input", "tbody"}
NL = chr(10)


class _Shape(HTMLParser):
    """Reduces HTML to the sequence of tags and text a reader actually perceives.

    Attributes are dropped, whitespace is collapsed, and a <pre> becomes one blob of text -
    GitHub colours its code with spans, this page colours it with different ones, and that
    difference is not what this comparison is about.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tokens: list[str] = []
        self.pre = 0
        self.buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag == "pre":
            self.pre += 1
            self.tokens.append("<pre>")
        elif not self.pre and tag not in _SKIP_TAGS:
            self.tokens.append(f"<{tag}>")

    def handle_startendtag(self, tag: str, attrs: object) -> None:
        if not self.pre and tag not in _SKIP_TAGS:
            self.tokens.append(f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre" and self.pre:
            self.pre -= 1
            self.tokens.append(" ".join("".join(self.buf).split()))
            self.tokens.append("</pre>")
            self.buf = []
        elif not self.pre and tag not in _SKIP_TAGS:
            self.tokens.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self.pre:
            self.buf.append(data)
            return
        text = " ".join(data.split())
        if text:
            self.tokens.append(text)


def _shape(html: str) -> list[str]:
    parser = _Shape()
    parser.feed(html)
    merged: list[str] = []
    for token in parser.tokens:
        # Adjacent text is joined so that the same sentence, split differently by tags that
        # were dropped, still compares equal.
        if merged and not token.startswith("<") and not merged[-1].startswith("<"):
            merged[-1] = f"{merged[-1]} {token}"
        else:
            merged.append(token)
    return merged


def test_markdown_matches_github_on_recorded_samples() -> None:
    """The page and GitHub must render the same file the same way.

    Readers move between the two - the page links to GitHub on every problem - so a
    difference reads as one of them being broken. The fixture holds GitHub's own output for
    constructs taken from real problem statements: images, HTML tables with style attributes,
    a table whose last line is not a row, nested and loose lists, hints, and the overlapping
    emphasis runs LeetCode writes, such as "*the **smallest* *subsequence** of*". Regenerate
    it with tests/fixtures/gen_github_markdown.py when a construct is added.
    """
    node = _node()
    if node is None:
        pytest.skip("node is not available")

    fixture = Path(__file__).parent / "fixtures" / "github_markdown.json"
    samples = json.loads(fixture.read_text(encoding="utf-8"))

    script = """
    import { readFileSync } from "node:fs";
    const src = readFileSync(process.env.APP_JS, "utf8");
    const mod = src.slice(src.indexOf("/* ---------- Markdown"),
      src.indexOf("/* ---------- fetching")) + "export { markdown };";
    const { markdown } = await import("data:text/javascript," + encodeURIComponent(mod));
    const samples = JSON.parse(readFileSync(process.env.FIXTURE, "utf8"));
    const out = {};
    for (const [name, s] of Object.entries(samples)) out[name] = markdown(s.markdown);
    process.stdout.write(JSON.stringify(out));
    """
    import os

    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "APP_JS": str(_asset("assets/app.js")), "FIXTURE": str(fixture)},
    )
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)

    differing = {
        name: (_shape(rendered[name]), _shape(sample["github"]))
        for name, sample in samples.items()
        if _shape(rendered[name]) != _shape(sample["github"])
    }
    assert not differing, "\n".join(
        f"{name}{NL}  ours  : {ours}{NL}  github: {theirs}"
        for name, (ours, theirs) in differing.items()
    )
