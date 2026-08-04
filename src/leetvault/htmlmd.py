"""Minimal HTML -> Markdown conversion for LeetCode problem statements.

Deliberately narrow: it handles exactly the tag vocabulary LeetCode's `question.content`
actually uses, measured across a real account's solved problems rather than guessed -
`p, strong, b, em, i, code, pre, ul, ol, li, sup, sub, br, img, a, u, span, div, font`
plus `table/thead/tbody/tr/td/th`.

Markdown has no syntax for tables-from-HTML or underline, so those tags are passed through
as raw HTML (which Markdown explicitly permits and GitHub renders) instead of being
flattened into mangled text. Everything else becomes real Markdown, so the file stays
readable as plain text in an editor, in `git diff`, and in non-GitHub viewers.

Built on stdlib `html.parser` rather than a regex pass, so nesting is tracked correctly,
and rather than taking a new dependency for one feature.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

# Emitted verbatim as HTML: Markdown cannot express these, and flattening them loses data.
_PASSTHROUGH_TREES = {"table"}
_PASSTHROUGH_INLINE = {"u"}

# Purely presentational wrappers - drop the tag, keep the text inside.
_UNWRAP = {"span", "font", "div"}

_VOID_TAGS = {"br", "img", "hr", "meta", "link"}


class _MarkdownConverter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._list_stack: list[str] = []
        self._ordered_index: list[int] = []
        self._in_pre = False
        self._pending_href: str | None = None
        self._raw_tag: str | None = None
        self._raw_depth = 0

    # --- raw HTML passthrough -------------------------------------------------

    def _start_raw(self, tag: str) -> None:
        self._raw_tag = tag
        self._raw_depth = 1
        self._out.append("\n\n")
        self._out.append(self.get_starttag_text() or f"<{tag}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._raw_tag is not None:
            self._out.append(self.get_starttag_text() or f"<{tag}>")
            if tag == self._raw_tag:
                self._raw_depth += 1
            return

        if tag in _PASSTHROUGH_TREES:
            self._start_raw(tag)
            return
        if tag in _PASSTHROUGH_INLINE:
            self._out.append(f"<{tag}>")
            return
        if tag in _UNWRAP:
            return

        # Inside a fenced block nothing renders as Markdown, so emphasis markers would show
        # up literally. LeetCode wraps "Input:"/"Output:" in <strong> inside its <pre>
        # example blocks, so this matters on nearly every problem.
        if self._in_pre and tag in {"strong", "b", "em", "i", "code"}:
            return

        attrd = dict(attrs)
        if tag == "br":
            self._out.append("\n")
        elif tag == "p":
            self._out.append("\n\n")
        elif tag in {"strong", "b"}:
            self._out.append("**")
        elif tag in {"em", "i"}:
            self._out.append("*")
        elif tag == "code":
            self._out.append("`")
        elif tag == "pre":
            self._in_pre = True
            self._out.append("\n\n```\n")
        elif tag == "sup":
            self._out.append("^")
        elif tag == "sub":
            self._out.append("_")
        elif tag in {"ul", "ol"}:
            self._list_stack.append(tag)
            self._ordered_index.append(0)
            self._out.append("\n")
        elif tag == "li":
            indent = "  " * max(len(self._list_stack) - 1, 0)
            if self._list_stack and self._list_stack[-1] == "ol":
                self._ordered_index[-1] += 1
                self._out.append(f"\n{indent}{self._ordered_index[-1]}. ")
            else:
                self._out.append(f"\n{indent}- ")
        elif tag == "img":
            self._out.append(f"![{attrd.get('alt') or ''}]({attrd.get('src') or ''})")
        elif tag == "a":
            self._pending_href = attrd.get("href")
            self._out.append("[")
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "blockquote":
            self._out.append("\n\n> ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Self-closing form (e.g. <br />) must not also run the end-tag path.
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if self._raw_tag is not None:
            if tag in _VOID_TAGS:
                return
            self._out.append(f"</{tag}>")
            if tag == self._raw_tag:
                self._raw_depth -= 1
                if self._raw_depth == 0:
                    self._raw_tag = None
                    self._out.append("\n\n")
            return

        if tag in _PASSTHROUGH_INLINE:
            self._out.append(f"</{tag}>")
            return
        if tag in _UNWRAP:
            return
        if self._in_pre and tag in {"strong", "b", "em", "i", "code"}:
            return
        if tag == "li":
            return  # the next <li> supplies its own newline; don't loosen the list

        if tag in {"strong", "b"}:
            self._out.append("**")
        elif tag in {"em", "i"}:
            self._out.append("*")
        elif tag == "code":
            self._out.append("`")
        elif tag == "pre":
            self._in_pre = False
            self._out.append("\n```\n\n")
        elif tag in {"ul", "ol"}:
            if self._list_stack:
                self._list_stack.pop()
                self._ordered_index.pop()
            self._out.append("\n")
        elif tag == "a":
            self._out.append(f"]({self._pending_href or ''})")
            self._pending_href = None
        elif tag in {"p", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._out.append("\n")

    def handle_data(self, data: str) -> None:
        if self._raw_tag is not None or self._in_pre:
            self._out.append(data)
        else:
            # Collapse the newlines/indentation LeetCode's HTML carries purely for source
            # formatting; real line structure comes from the block tags above.
            self._out.append(re.sub(r"\s+", " ", data))

    def result(self) -> str:
        text = "".join(self._out)
        text = text.replace("\xa0", " ")  # &nbsp;
        text = re.sub(r"```\n\n+", "```\n", text)  # no leading blank line in a fence
        text = re.sub(r"\n\n+```", "\n```", text)  # nor a trailing one
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_markdown(html: str) -> str:
    """Convert a LeetCode problem-statement HTML fragment into Markdown."""
    if not html:
        return ""
    converter = _MarkdownConverter()
    converter.feed(html)
    converter.close()
    return converter.result()
