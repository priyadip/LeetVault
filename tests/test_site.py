from __future__ import annotations

import json
import shutil
import subprocess
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
    const mod = src.slice(src.indexOf("function esc("), src.indexOf("/* ---------- fetching"))
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
      fence: /<pre><code class="code">x = 1  # a &lt; b<\\/code><\\/pre>/.test(html),
      table: /<th>Step<\\/th>/.test(html) && /<td>store <code>2<\\/code><\\/td>/.test(html),
      bullets: /<ul><li>bulleted<\\/li><\\/ul>/.test(html),
      numbered: /<ol><li>numbered<\\/li><\\/ol>/.test(html),
      quote: /<blockquote>/.test(html),
      escaped: !/<img/i.test(hostile),
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
    # Folded away entirely rather than left as a strip that still costs width.
    assert "body.rail-hidden section{padding-left:56px}" in css
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
