"""Data model.

Record-keeping rules (ISO 9001 / ISO 22000 clause 7.2 evidence):
- ModuleVersion is an immutable snapshot of the training content and quiz as issued.
- QuizAttempt and Acknowledgment rows are only ever inserted, never updated
  (except the supervisor sign-off fields, which are themselves audit-logged).
- Every state change is written to AuditLog, which is hash-chained so that
  edits made directly in the database can be detected (see app/audit.py).
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Trainee(Base):
    __tablename__ = "trainees"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(30))  # international format, digits only
    role: Mapped[str] = mapped_column(String(50), default="Technician")
    preferred_lang: Mapped[str] = mapped_column(String(5), default="en")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Module(Base):
    __tablename__ = "modules"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    versions: Mapped[list["ModuleVersion"]] = relationship(back_populates="module")


class ModuleVersion(Base):
    __tablename__ = "module_versions"
    __table_args__ = (UniqueConstraint("module_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id"))
    version: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    source_doc: Mapped[str] = mapped_column(String(200), default="")  # e.g. SMP-MAINT-TRAIN-002 v1
    pass_mark: Mapped[int] = mapped_column(Integer, default=80)  # percent
    questions_per_attempt: Mapped[int] = mapped_column(Integer, default=5)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    acknowledgment_text: Mapped[str] = mapped_column(Text)
    questions: Mapped[list] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    module: Mapped[Module] = relationship(back_populates="versions")
    videos: Mapped[list["Video"]] = relationship(back_populates="module_version")


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (UniqueConstraint("module_version_id", "lang"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    module_version_id: Mapped[int] = mapped_column(ForeignKey("module_versions.id"))
    lang: Mapped[str] = mapped_column(String(5))
    filename: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_by: Mapped[str] = mapped_column(String(100))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    module_version: Mapped[ModuleVersion] = relationship(back_populates="videos")


class Assignment(Base):
    """One personal link sent to one trainee, covering one or more modules."""
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    trainee_id: Mapped[int] = mapped_column(ForeignKey("trainees.id"))
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trainee: Mapped[Trainee] = relationship()
    items: Mapped[list["AssignmentItem"]] = relationship(back_populates="assignment")


class AssignmentItem(Base):
    __tablename__ = "assignment_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"))
    module_version_id: Mapped[int] = mapped_column(ForeignKey("module_versions.id"))
    # pending -> watched -> passed | failed (attempts exhausted)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignment: Mapped[Assignment] = relationship(back_populates="items")
    module_version: Mapped[ModuleVersion] = relationship()
    attempts: Mapped[list["QuizAttempt"]] = relationship(back_populates="item")
    acknowledgment: Mapped["Acknowledgment | None"] = relationship(back_populates="item", uselist=False)


class ViewEvent(Base):
    """Supporting evidence only: video opened / played / ended, per language."""
    __tablename__ = "view_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("assignment_items.id"), index=True)
    lang: Mapped[str] = mapped_column(String(5))
    event: Mapped[str] = mapped_column(String(20))
    position_s: Mapped[int] = mapped_column(Integer, default=0)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("assignment_items.id"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    lang: Mapped[str] = mapped_column(String(5))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    question_ids: Mapped[list] = mapped_column(JSON)
    answers: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {qid: chosen_index}
    score_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    item: Mapped[AssignmentItem] = relationship(back_populates="attempts")


class Acknowledgment(Base):
    __tablename__ = "acknowledgments"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("assignment_items.id"), unique=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("quiz_attempts.id"))
    statement: Mapped[str] = mapped_column(Text)
    typed_name: Mapped[str] = mapped_column(String(200))
    employee_id: Mapped[str] = mapped_column(String(50))
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(400), default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    certificate_no: Mapped[str] = mapped_column(String(40), unique=True)
    supervisor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    supervisor_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    item: Mapped[AssignmentItem] = relationship(back_populates="acknowledgment")
    attempt: Mapped[QuizAttempt] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(50))
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


# ---------------------------------------------------------------------------
# Courses group lessons. In code a lesson is a `Module` (one quiz + one video
# per language); on screen it is called a "Lesson". Courses and lessons are
# created and revised in the admin pages (app/authoring.py). The course tables
# are new tables only, so existing databases need no migration (create_all adds them).
# ---------------------------------------------------------------------------
class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=100)  # order on screen
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    lessons: Mapped[list["CourseLesson"]] = relationship(
        back_populates="course", order_by="CourseLesson.position", cascade="all, delete-orphan")


class CourseLesson(Base):
    __tablename__ = "course_lessons"
    __table_args__ = (UniqueConstraint("course_id", "module_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)  # 1-based lesson number
    course: Mapped[Course] = relationship(back_populates="lessons")
    module: Mapped[Module] = relationship()


class CourseCompletion(Base):
    """Insert-only: written when a trainee has passed and acknowledged every lesson
    (current version) of a course. `lessons` is a snapshot of the evidence."""
    __tablename__ = "course_completions"
    id: Mapped[int] = mapped_column(primary_key=True)
    trainee_id: Mapped[int] = mapped_column(ForeignKey("trainees.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    course_title: Mapped[str] = mapped_column(String(200))
    lessons: Mapped[list] = mapped_column(JSON)  # [{position, title, version, module_version_id, certificate_no, ...}]
    lessons_key: Mapped[str] = mapped_column(String(400))  # sorted module_version_ids, to avoid duplicates
    certificate_no: Mapped[str] = mapped_column(String(40), unique=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    trainee: Mapped[Trainee] = relationship()
    course: Mapped[Course] = relationship()
