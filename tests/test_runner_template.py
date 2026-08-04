"""Tests for the generated runner - executed as a real script against real solution files.

The runner ships as a template rendered into the user's repo, so these tests render it
the same way sync does and then actually run it, rather than importing internals.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from leetvault.git_writer import write_run_shim, write_shared_runner


def _make_problem(
    repo: Path,
    slug: str,
    solution: str,
    runner: dict[str, object],
    *,
    frontend_id: int = 1,
    title: str = "Two Sum",
) -> Path:
    p_dir = repo / "Problems" / slug
    p_dir.mkdir(parents=True, exist_ok=True)
    (p_dir / "latest.py").write_text(solution, encoding="utf-8")
    (p_dir / "metadata.json").write_text(
        json.dumps(
            {"frontend_id": frontend_id, "title": title, "difficulty": "Easy", "runner": runner}
        ),
        encoding="utf-8",
    )
    write_shared_runner(repo)
    write_run_shim(repo, slug)
    return p_dir


def _run(p_dir: Path) -> str:
    result = subprocess.run(
        [sys.executable, str(p_dir / "run.py")], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_runner_executes_solution_against_examples(tmp_path: Path) -> None:
    p_dir = _make_problem(
        tmp_path,
        "two-sum",
        "class Solution:\n"
        "    def twoSum(self, nums, target):\n"
        "        seen = {}\n"
        "        for i, n in enumerate(nums):\n"
        "            if target - n in seen:\n"
        "                return [seen[target - n], i]\n"
        "            seen[n] = i\n",
        {
            "method": "twoSum",
            "param_types": ["integer[]", "integer"],
            "example_testcases": "[2,7,11,15]\n9\n[3,2,4]\n6",
        },
    )
    out = _run(p_dir)
    assert "-> [0, 1]" in out
    assert "-> [1, 2]" in out


def test_runner_provides_names_leetcode_preloads(tmp_path: Path) -> None:
    """Real stored solutions use List[int], gcd() and bisect.bisect_right() with no
    import, because LeetCode's judge preloads them - all three broke real problems."""
    p_dir = _make_problem(
        tmp_path,
        "preloaded",
        "class Solution:\n"
        "    def check(self, nums: List[int]) -> int:\n"
        "        return gcd(nums[0], nums[1]) + bisect.bisect_right(nums, 0) + int(inf > 0)\n",
        {
            "method": "check",
            "param_types": ["integer[]"],
            "example_testcases": "[4,6]",
        },
    )
    out = _run(p_dir)
    assert "raised" not in out
    assert "-> 3" in out  # gcd(4,6)=2, bisect_right([4,6],0)=0, inf>0 -> 1


def test_runner_handles_nested_json_types(tmp_path: Path) -> None:
    p_dir = _make_problem(
        tmp_path,
        "grid",
        "class Solution:\n    def count(self, board):\n        return len(board)\n",
        {
            "method": "count",
            "param_types": ["character[][]"],
            "example_testcases": '[["a","b"],["c","d"]]',
        },
    )
    assert "-> 2" in _run(p_dir)


def test_runner_refuses_design_problems(tmp_path: Path) -> None:
    p_dir = _make_problem(
        tmp_path,
        "lru-cache",
        "class Solution:\n    pass\n",
        {"method": None, "param_types": [], "example_testcases": ""},
    )
    out = _run(p_dir)
    assert "no single entry point" in out


def test_runner_refuses_non_json_param_types(tmp_path: Path) -> None:
    p_dir = _make_problem(
        tmp_path,
        "reverse-list",
        "class Solution:\n    def reverseList(self, head):\n        return head\n",
        {
            "method": "reverseList",
            "param_types": ["ListNode"],
            "example_testcases": "[1,2,3]",
        },
    )
    out = _run(p_dir)
    assert "custom construction" in out


def test_runner_reports_a_raising_solution_without_crashing(tmp_path: Path) -> None:
    p_dir = _make_problem(
        tmp_path,
        "boom",
        "class Solution:\n    def go(self, nums):\n        raise ValueError('nope')\n",
        {"method": "go", "param_types": ["integer[]"], "example_testcases": "[1]"},
    )
    out = _run(p_dir)
    assert "raised ValueError: nope" in out
