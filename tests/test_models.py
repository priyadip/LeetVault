from pathlib import Path

from sqlalchemy import select

from leetvault.db import make_engine, make_session_factory, session_scope
from leetvault.models import Problem, Submission, SubmissionCode, Topic


def test_round_trip_problem_submission_code_topics(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "leetvault.db")
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        problem = Problem(
            question_id=1,
            frontend_id=1,
            title="Two Sum",
            title_slug="two-sum",
            difficulty="Easy",
            paid_only=False,
            url="https://leetcode.com/problems/two-sum/",
        )
        array_topic = Topic(id=1, name="Array")
        hashmap_topic = Topic(id=2, name="Hash Table")
        problem.topics = [array_topic, hashmap_topic]

        submission = Submission(
            submission_id=100,
            question_id=1,
            lang="python3",
            status="Accepted",
            runtime="52 ms",
            memory="16.1 MB",
            runtime_percentile=88.5,
            memory_percentile=42.1,
            timestamp=1_700_000_000,
            code_hash="abc123",
            is_accepted=True,
        )
        submission.code = SubmissionCode(code="class Solution:\n    pass\n")
        problem.submissions = [submission]

        session.add(problem)

    with session_scope(factory) as session:
        stored = session.scalar(select(Problem).where(Problem.title_slug == "two-sum"))
        assert stored is not None
        assert stored.title == "Two Sum"
        assert {t.name for t in stored.topics} == {"Array", "Hash Table"}
        assert len(stored.submissions) == 1
        assert stored.submissions[0].code is not None
        assert stored.submissions[0].code.code.startswith("class Solution")
        assert stored.submissions[0].runtime_percentile == 88.5
