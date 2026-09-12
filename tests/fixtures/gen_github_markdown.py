"""Records GitHub's rendering of the constructs these files contain.

The samples are drawn from real problem statements and analyses - overlapping emphasis runs
and all - so the fixture is evidence rather than invention. Regenerate with:

    python gen_fixture.py > tests/fixtures/github_markdown.json
"""

import json
import subprocess
import sys

U = "https://assets.leetcode.com/uploads/2018/10/22/rainwatertrap.png"

SAMPLES: dict[str, str] = {
    "image": f"**Example 1:**\n ![]({U})\n```\nInput: height = [0,1]\n```",
    "image_with_alt": f"Here it is: ![elevation map]({U}) and text after.",
    "html_table": (
        "Seven symbols:\n\n<table>\n\t<thead>\n\t\t<tr>\n\t\t\t<th>Symbol</th>\n"
        "\t\t\t<th>Value</th>\n\t\t</tr>\n\t</thead>\n\t<tbody>\n\t\t<tr>\n"
        "\t\t\t<td>I</td>\n\t\t\t<td>1</td>\n\t\t</tr>\n\t\t<tr>\n\t\t\t<td>V</td>\n"
        "\t\t\t<td>5</td>\n\t\t</tr>\n\t</tbody>\n</table>\n\nAfter the table."
    ),
    "html_table_with_attributes": (
        '<table>\n<tr>\n<th style="border: 1px solid black;"><code>i</code></th>\n'
        '<th style="border: 1px solid black;"><code>mx<sub>i</sub></code></th>\n</tr>\n</table>'
    ),
    "pipe_table_trailing_line": (
        "| Step | p | Action |\n|------|---|--------|\n| 1 | 7 | max_p = 0 |\n"
        "| 2 | 1 | max_p = 0 |\nResult: 5.\n\n## Complexity"
    ),
    "pipe_table_alignment": ("| Left | Mid | Right |\n|:-----|:---:|------:|\n| a | b | c |"),
    "pipe_table_escaped_pipe": "| A | B |\n|---|---|\n| a \\| b | c |",
    "nested_loose_list": (
        "- A valid sequence of moves is as follows:\n\n"
        "  - Move 1: From `(0, 0)` to `(0, 1)`.\n"
        "  - Move 2: From `(0, 1)` to `(1, 1)`.\n\n"
        "- The student collects all the litter using 2 moves."
    ),
    "tight_list": (
        "- **Step 1** - For `curr`, do the thing.\n"
        "- **Step 2** - Then do the other thing.\n"
        "- **Step 3** - Return `ans`."
    ),
    "deep_indent_not_a_list": (
        "5. While `size < n`:\n"
        "   a. Set `prev = dummy`.\n"
        "   b. While `curr` is not `None`:\n"
        "        - `left = curr`.\n"
        "        - `right = split(left, size)`."
    ),
    "empty_list_item": "Values:\n\n-\n-\n- Sum of the first 4 odd numbers `sumOdd = 16`",
    "ordered_list_start": "3. third\n4. fourth\n5. fifth",
    "details_hint": (
        "## Hints\n\n<details>\n<summary>Hint 1</summary>\n\nUse a hash map.\n\n</details>\n"
        "<details>\n<summary>Hint 2</summary>\n\nThen a `set`.\n\n</details>"
    ),
    "u_tag": "Coin 3 produces: 3, 6, <u>**9**</u>, 12, etc.",
    "u_tag_in_code_span": 'The subsequence `"<u>a</u>b<u>c</u>"` is valid.',
    "emphasis_overlapping": (
        "Given a string `s`, return *the **lexicographically smallest* "
        "*subsequence** of* `s` *that contains all the distinct characters*."
    ),
    "emphasis_spaced_delimiter": ("`n` is divisible by the **sum **of the following two values:"),
    "emphasis_quadruple": (
        "Given two strings s and t, return *the number of distinct* "
        "***subsequences**** of *s* which equals *t.*"
    ),
    "emphasis_underscore_intraword": (
        "Set `min_s` and _emphasis_ and snake_case_name and __strong__."
    ),
    "code_span_across_lines": (
        'The mapping is:\n\n`"1" -> A\n"2" -> B\n...\n"26" -> Z`\n\nGiven a string, decode it.'
    ),
    "emphasis_after_code_span": "Return the length of the subarray of `nums` *.*",
    "raw_html_link": 'Visit <a href="https://example.com/x">the site</a> today.',
    "raw_html_image": (
        'Diagram: <img src="https://assets.leetcode.com/uploads/x.png" alt="map"> after.'
    ),
    "raw_html_unsafe_link": 'Click <a href="javascript:alert(1)">here</a> please.',
    "hard_break": ('- `y = 2`, `cnt[2] = 1`.  \nBuild suffix from `cnt`.  \nReturn `"bca"`.'),
    "bare_url": "See https://leetcode.com/problems/two-sum/ for details.",
    "link_with_emphasis": (
        "[**Container With Most Water**](https://leetcode.com/problems/x/) - Medium"
    ),
    "angle_not_a_tag": "| a | b |\n|---|---|\n| x>=fm, x<smi | 2 |",
    "fenced_python": "```python\ndef f(x):\n    return x  # a < b\n```",
    "indented_code": "Paragraph.\n\n    line one\n    line two\n\nAfter.",
    "setext_and_hr": "Heading text\n---\n\nBody.\n\n---\n\n_Footer text._",
    "blockquote": "> Note that the array is **sorted**.\n> Second line.",
    "backslash_escape": "Literal \\*not emphasis\\* and \\| pipe.",
    "entities": "Compare a &lt; b and &amp; and &#39;quoted&#39;.",
    "strikethrough": "This is ~~removed~~ text.",
}


def github(md: str) -> str:
    out = subprocess.run(
        ["gh", "api", "--method", "POST", "/markdown", "--input", "-"],
        input=json.dumps({"text": md, "mode": "markdown"}),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if out.returncode:
        raise SystemExit(f"gh failed: {out.stderr.strip()[:300]}")
    return out.stdout


def main() -> None:
    recorded = {name: {"markdown": md, "github": github(md)} for name, md in SAMPLES.items()}
    json.dump(recorded, sys.stdout, indent=1, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
