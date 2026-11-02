"""Imports training modules from content/modules/<slug>/module.yaml.

Content lives in git so every change is reviewed and versioned (document
control). Rule: once a version is published, its content cannot change. Edit
the YAML and bump `version` instead, which creates a new ModuleVersion; old
records keep pointing at the version the trainee actually took.
"""
import hashlib
import json
from dataclasses import dataclass, field

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .config import LANGUAGES, settings
from .models import Course, CourseLesson, Module, ModuleVersion

REQUIRED = ("slug", "title", "version", "acknowledgment", "questions")


@dataclass
class SyncReport:
    created: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def validate(data: dict, path: str) -> list[str]:
    errs = [f"{path}: missing '{k}'" for k in REQUIRED if k not in data]
    if errs:
        return errs
    ids = set()
    for i, q in enumerate(data["questions"]):
        where = f"{path}: question #{i + 1}"
        qid = q.get("id")
        if not qid or qid in ids:
            errs.append(f"{where}: missing or duplicate id")
        ids.add(qid)
        if "en" not in q.get("text", {}) or "en" not in q.get("options", {}):
            errs.append(f"{where}: English text/options required")
            continue
        n = len(q["options"]["en"])
        if not isinstance(q.get("answer"), int) or not 0 <= q["answer"] < n:
            errs.append(f"{where}: 'answer' must be an option index 0..{n - 1}")
        for lang, opts in q["options"].items():
            if lang not in LANGUAGES:
                errs.append(f"{where}: unknown language '{lang}'")
            elif len(opts) != n:
                errs.append(f"{where}: '{lang}' has {len(opts)} options, English has {n}")
    per = data.get("questions_per_attempt", 5)
    if per > len(data["questions"]):
        errs.append(f"{path}: questions_per_attempt ({per}) > question bank ({len(data['questions'])})")
    return errs


def content_hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def sync(db: Session, actor: str) -> SyncReport:
    report = SyncReport()
    for path in sorted(settings.content_dir.glob("modules/*/module.yaml")):
        rel = str(path.relative_to(settings.content_dir))
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            report.errors.append(f"{rel}: invalid YAML ({e})")
            continue
        errs = validate(data, rel)
        if errs:
            report.errors.extend(errs)
            continue
        version = str(data["version"])
        h = content_hash(data)
        module = db.scalar(select(Module).where(Module.slug == data["slug"]))
        if module is None:
            module = Module(slug=data["slug"], title=data["title"])
            db.add(module)
            db.flush()
        existing = db.scalar(select(ModuleVersion).where(
            ModuleVersion.module_id == module.id, ModuleVersion.version == version))
        label = f"{data['slug']} v{version}"
        if existing:
            if existing.content_hash == h:
                report.unchanged.append(label)
            else:
                report.errors.append(f"{label}: content changed but version not bumped. "
                                     "Published versions are frozen; increase 'version'.")
            continue
        mv = ModuleVersion(
            module_id=module.id, version=version, title=data["title"],
            summary=data.get("summary", ""), source_doc=data.get("source_doc", ""),
            pass_mark=int(data.get("pass_mark", 80)),
            questions_per_attempt=int(data.get("questions_per_attempt", 5)),
            max_attempts=int(data.get("max_attempts", 3)),
            acknowledgment_text=data["acknowledgment"].strip(),
            questions=data["questions"], content_hash=h,
        )
        db.add(mv)
        db.flush()
        module.title = data["title"]
        module.current_version_id = mv.id
        audit.log(db, actor, "publish_version", "module_version", mv.id,
                  {"slug": data["slug"], "version": version, "content_hash": h})
        report.created.append(label)
    db.flush()
    _sync_courses(db, actor, report)
    db.commit()
    return report


def _sync_courses(db: Session, actor: str, report: SyncReport) -> None:
    """content/courses/<slug>/course.yaml: title, summary, position, lessons (module slugs in order).
    Course structure is not version-frozen like lesson content; every change is audit-logged."""
    for path in sorted(settings.content_dir.glob("courses/*/course.yaml")):
        rel = str(path.relative_to(settings.content_dir))
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            report.errors.append(f"{rel}: invalid YAML ({e})")
            continue
        missing = [k for k in ("slug", "title", "lessons") if not data.get(k)]
        if missing:
            report.errors.append(f"{rel}: missing {', '.join(missing)}")
            continue
        slugs = list(data["lessons"])
        if len(set(slugs)) != len(slugs):
            report.errors.append(f"{rel}: a lesson is listed twice")
            continue
        modules = {m.slug: m for m in db.scalars(select(Module).where(Module.slug.in_(slugs)))}
        unknown = [s for s in slugs if s not in modules]
        if unknown:
            report.errors.append(f"{rel}: unknown lesson(s) {', '.join(unknown)} (no content/modules/<slug>/module.yaml)")
            continue
        course = db.scalar(select(Course).where(Course.slug == data["slug"]))
        new = course is None
        if new:
            course = Course(slug=data["slug"], title=data["title"])
            db.add(course)
        before = {"title": course.title, "summary": course.summary, "position": course.position,
                  "lessons": [cl.module.slug for cl in course.lessons]} if not new else None
        course.title = data["title"]
        course.summary = (data.get("summary") or "").strip()
        course.position = int(data.get("position", 100))
        if new or before["lessons"] != slugs:
            course.lessons.clear()
            db.flush()
            for i, s in enumerate(slugs, 1):
                course.lessons.append(CourseLesson(module_id=modules[s].id, position=i))
        db.flush()
        after = {"title": course.title, "summary": course.summary, "position": course.position, "lessons": slugs}
        label = f"course {data['slug']} ({len(slugs)} lessons)"
        if new or before != after:
            audit.log(db, actor, "course_created" if new else "course_updated", "course", course.id, after)
            report.created.append(label)
        else:
            report.unchanged.append(label)
