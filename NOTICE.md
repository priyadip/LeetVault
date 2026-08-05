# Third-party notices

leetvault is MIT licensed (see [LICENSE](LICENSE)). It also incorporates work from the
project below, used under its own licence.

## leetcode-helper

The prompt in `src/leetvault/ai/prompt.py` — used to generate each problem's `analysis.md` —
is adapted from **leetcode-helper** by Aman Attar:

- Source: https://github.com/amanattar/leetcode-helper
- Licence: MIT

The original is a Claude/Codex skill that guides an agent to *solve* an interview problem
end to end. leetvault's need is different: the solution already exists and belongs to the
user, so the original's seven-part structure (problem understanding, approach, algorithm,
code, line-by-line explanation, dry run, complexity and edge cases) is retained but
re-pointed at explaining and critiquing existing code rather than writing new code.

```
MIT License

Copyright (c) Aman Attar

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Each generated `analysis.md` also carries this attribution in its footer.
