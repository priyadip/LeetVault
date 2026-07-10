"""SQLAlchemy 2.0 declarative models for the leetvault SQLite database.

Schema mirrors the "Data model (SQLite)" section of CLAUDE.md exactly.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Problem(Base):
    __tablename__ = "problems"

    question_id: Mapped[int] = mapped_column(primary_key=True)
    frontend_id: Mapped[int]
    title: Mapped[str]
    title_slug: Mapped[str] = mapped_column(unique=True, index=True)
    difficulty: Mapped[str]
    paid_only: Mapped[bool] = mapped_column(default=False)
    url: Mapped[str]

    submissions: Mapped[list[Submission]] = relationship(
        back_populates="problem", cascade="all, delete-orphan"
    )
    topics: Mapped[list[Topic]] = relationship(
        secondary="problem_topics", back_populates="problems"
    )


class Submission(Base):
    __tablename__ = "submissions"

    submission_id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("problems.question_id"), index=True)
    lang: Mapped[str]
    status: Mapped[str]
    runtime: Mapped[str | None] = mapped_column(default=None)
    memory: Mapped[str | None] = mapped_column(default=None)
    runtime_percentile: Mapped[float | None] = mapped_column(default=None)
    memory_percentile: Mapped[float | None] = mapped_column(default=None)
    timestamp: Mapped[int] = mapped_column(index=True)
    code_hash: Mapped[str]
    is_accepted: Mapped[bool]

    problem: Mapped[Problem] = relationship(back_populates="submissions")
    code: Mapped[SubmissionCode | None] = relationship(
        back_populates="submission", cascade="all, delete-orphan", uselist=False
    )


class SubmissionCode(Base):
    __tablename__ = "submission_code"

    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.submission_id"), primary_key=True
    )
    code: Mapped[str]

    submission: Mapped[Submission] = relationship(back_populates="code")


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)

    problems: Mapped[list[Problem]] = relationship(
        secondary="problem_topics", back_populates="topics"
    )


class ProblemTopic(Base):
    __tablename__ = "problem_topics"

    question_id: Mapped[int] = mapped_column(ForeignKey("problems.question_id"), primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), primary_key=True)


class SyncState(Base):
    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    site: Mapped[str] = mapped_column(unique=True, index=True)
    last_offset: Mapped[int] = mapped_column(default=0)
    last_submission_id: Mapped[int | None] = mapped_column(default=None)
    last_synced_timestamp: Mapped[int | None] = mapped_column(default=None)
    last_full_import_completed_at: Mapped[int | None] = mapped_column(default=None)
