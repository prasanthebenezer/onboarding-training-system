"""Course logic: lesson order, locking, and course completion.

A lesson is locked while an EARLIER lesson of the same course in the SAME
assignment is not yet passed. Lessons assigned on their own (e.g. a refresher
on lesson 4) are never locked by lessons that were not assigned.
"""
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .models import (Acknowledgment, Assignment, AssignmentItem, Course, CourseCompletion, CourseLesson,
                     Module, ModuleVersion, Trainee, utcnow)


@dataclass
class LessonRow:
    item: AssignmentItem
    number: int | None = None      # lesson number within its course
    total: int | None = None       # lessons in the course
    locked_by: AssignmentItem | None = None


@dataclass
class CourseGroup:
    course: Course | None          # None = lessons that belong to no course
    rows: list[LessonRow] = field(default_factory=list)
    completion: CourseCompletion | None = None


def lesson_index(db: Session) -> dict[int, tuple[Course, int, int]]:
    """module_id -> (course, lesson number, lessons in course). First course wins if a lesson is in two."""
    idx = {}
    for c in db.scalars(select(Course).where(Course.active).order_by(Course.position, Course.title)):
        for cl in c.lessons:
            idx.setdefault(cl.module_id, (c, cl.position, len(c.lessons)))
    return idx


def grouped(db: Session, a: Assignment) -> list[CourseGroup]:
    idx = lesson_index(db)
    groups: dict[int | None, CourseGroup] = {}
    for item in a.items:
        info = idx.get(item.module_version.module_id)
        key = info[0].id if info else None
        g = groups.setdefault(key, CourseGroup(info[0] if info else None))
        g.rows.append(LessonRow(item, info[1] if info else None, info[2] if info else None))
    for g in groups.values():
        g.rows.sort(key=lambda r: (r.number or 0, r.item.id))
        blocker = None
        for r in g.rows:
            if g.course is not None and blocker is not None:
                r.locked_by = blocker
            if g.course is not None and r.item.status != "passed" and blocker is None:
                blocker = r.item
        if g.course is not None:
            g.completion = db.scalar(select(CourseCompletion).where(
                CourseCompletion.trainee_id == a.trainee_id, CourseCompletion.course_id == g.course.id)
                .order_by(CourseCompletion.id.desc()).limit(1))
    ordered = sorted(groups.values(), key=lambda g: (g.course is None, g.course.position if g.course else 0,
                                                     g.course.title if g.course else ""))
    return ordered


def locked_by(db: Session, item: AssignmentItem) -> AssignmentItem | None:
    for g in grouped(db, item.assignment):
        for r in g.rows:
            if r.item.id == item.id:
                return r.locked_by
    return None


def complete_courses(db: Session, trainee: Trainee, actor: str) -> list[CourseCompletion]:
    """After a lesson is acknowledged: record a CourseCompletion for every course whose
    lessons (current versions) the trainee has now all passed and acknowledged."""
    acks = {}
    for ack in db.scalars(select(Acknowledgment).join(AssignmentItem).join(Assignment)
                          .where(Assignment.trainee_id == trainee.id)):
        acks.setdefault(ack.item.module_version_id, ack)
    created = []
    for course in db.scalars(select(Course).where(Course.active)):
        if not course.lessons:
            continue
        evidence = []
        for cl in course.lessons:
            mv_id = cl.module.current_version_id
            ack = acks.get(mv_id)
            if ack is None:
                break
            mv = ack.item.module_version
            evidence.append({"position": cl.position, "title": mv.title, "version": mv.version,
                             "module_version_id": mv.id, "source_doc": mv.source_doc,
                             "certificate_no": ack.certificate_no, "score_pct": ack.attempt.score_pct,
                             "lang": ack.attempt.lang, "acknowledged_at": ack.at.isoformat()})
        else:
            key = ",".join(str(e["module_version_id"]) for e in sorted(evidence, key=lambda e: e["module_version_id"]))
            if db.scalar(select(CourseCompletion.id).where(
                    CourseCompletion.trainee_id == trainee.id, CourseCompletion.course_id == course.id,
                    CourseCompletion.lessons_key == key)):
                continue
            now = utcnow()
            cc = CourseCompletion(trainee_id=trainee.id, course_id=course.id, course_title=course.title,
                                  lessons=evidence, lessons_key=key, completed_at=now,
                                  certificate_no=f"CRS-{now:%Y%m%d}-{trainee.id:04d}{course.id:03d}{len(created)}")
            db.add(cc)
            db.flush()
            cc.certificate_no = f"CRS-{now:%Y%m%d}-{cc.id:06d}"
            audit.log(db, actor, "course_completed", "course_completion", cc.id, {
                "course": course.slug, "trainee": trainee.employee_id,
                "certificate_no": cc.certificate_no, "lessons": evidence})
            created.append(cc)
    return created


def assign_catalog(db: Session) -> list[tuple[Course | None, list[ModuleVersion]]]:
    """Current lesson versions grouped by course, for the Assign and Lessons pages."""
    idx = lesson_index(db)
    mods = db.scalars(select(Module).where(Module.active, Module.current_version_id.is_not(None))).all()
    groups: dict[int | None, tuple[Course | None, list]] = {}
    for m in mods:
        info = idx.get(m.id)
        key = info[0].id if info else None
        groups.setdefault(key, (info[0] if info else None, []))[1].append((info[1] if info else 0, m))
    out = []
    for course, lst in sorted(groups.values(), key=lambda g: (g[0] is None, g[0].position if g[0] else 0,
                                                             g[0].title if g[0] else "")):
        lst.sort(key=lambda x: (x[0], x[1].slug))
        out.append((course, [db.get(ModuleVersion, m.current_version_id) for _, m in lst]))
    return out


def lesson_order_key(db: Session):
    idx = lesson_index(db)

    def key(mv: ModuleVersion):
        info = idx.get(mv.module_id)
        return (info[0].position if info else 10**6, info[0].id if info else 0, info[1] if info else 0, mv.id)
    return key


__all__ = ["grouped", "locked_by", "complete_courses", "assign_catalog", "lesson_order_key", "CourseLesson"]
