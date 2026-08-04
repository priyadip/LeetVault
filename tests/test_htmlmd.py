from __future__ import annotations

from leetvault.htmlmd import html_to_markdown


def test_empty_input() -> None:
    assert html_to_markdown("") == ""


def test_paragraphs_and_inline_formatting() -> None:
    html = "<p>Given <code>nums</code> and <strong>target</strong>, return <em>indices</em>.</p>"
    assert html_to_markdown(html) == "Given `nums` and **target**, return *indices*."


def test_nbsp_becomes_plain_space() -> None:
    assert "\xa0" not in html_to_markdown("<p>a&nbsp;b</p>")


def test_unordered_list_is_tight() -> None:
    html = "<ul><li>first</li><li>second</li></ul>"
    assert html_to_markdown(html) == "- first\n- second"


def test_ordered_list_numbers_sequentially() -> None:
    html = "<ol><li>one</li><li>two</li><li>three</li></ol>"
    assert html_to_markdown(html) == "1. one\n2. two\n3. three"


def test_pre_becomes_fenced_block_without_emphasis_markers() -> None:
    # LeetCode wraps Input:/Output: in <strong> inside <pre>; inside a fence Markdown
    # isn't rendered, so emitting ** there would show literal asterisks to the reader.
    html = "<pre><strong>Input:</strong> nums = [1,2]\n<strong>Output:</strong> 3</pre>"
    result = html_to_markdown(html)
    assert result == "```\nInput: nums = [1,2]\nOutput: 3\n```"
    assert "**" not in result


def test_superscript_and_subscript() -> None:
    assert html_to_markdown("<p>10<sup>4</sup> and x<sub>i</sub></p>") == "10^4 and x_i"


def test_image_becomes_markdown_image() -> None:
    html = '<img alt="grid" src="https://example.com/a.png" />'
    assert html_to_markdown(html) == "![grid](https://example.com/a.png)"


def test_link_becomes_markdown_link() -> None:
    html = '<p>See <a href="https://example.com">docs</a>.</p>'
    assert html_to_markdown(html) == "See [docs](https://example.com)."


def test_table_is_passed_through_as_raw_html() -> None:
    # Markdown has no way to express an HTML table without lossy reformatting, and
    # flattening it destroys the data, so it is emitted verbatim (Markdown allows
    # inline HTML and GitHub renders it).
    html = "<p>before</p><table><tr><td>I</td><td>1</td></tr></table><p>after</p>"
    result = html_to_markdown(html)
    assert "<table>" in result
    assert "<td>I</td>" in result
    assert "</table>" in result
    assert result.startswith("before")
    assert result.endswith("after")


def test_underline_is_passed_through_since_markdown_lacks_it() -> None:
    assert html_to_markdown("<p>a <u>b</u> c</p>") == "a <u>b</u> c"


def test_presentational_wrappers_are_unwrapped() -> None:
    html = '<p><span style="color:red">red</span> and <font>font</font></p>'
    result = html_to_markdown(html)
    assert result == "red and font"
    assert "<span" not in result
    assert "<font>" not in result


def test_no_leftover_block_tags() -> None:
    html = "<div><p>one</p><p>two</p></div>"
    result = html_to_markdown(html)
    assert "<p>" not in result
    assert "<div>" not in result
    assert result == "one\n\ntwo"
