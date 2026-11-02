"""Creating and revising courses and lessons from the admin pages.

The database is the source of the training content. Document-control rule:
a published lesson version (ModuleVersion) never changes. Revising a lesson
publishes the next version; trainees' records keep pointing at the version
they actually took. Course structure (title, order, lesson list) is not
version-frozen, but every change is written to the audit log.
"""
import hashlib
import json
import os
import re
import shutil

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import audit
from .config import LANGUAGES, settings
from .models import Course, CourseLesson, Module, ModuleVersion, Video, utcnow

DEFAULT_ACK = ("I confirm that I have watched this training video and completed the assessment myself. "
               "I have understood the content of this lesson and will apply it in my work. "
               "I will ask my supervisor if anything is unclear.")
OTHER_LANGS = [code for code in LANGUAGES if code != "en"]


class ContentError(ValueError):
    """Raised with a list of messages the admin needs to fix."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# ---------- helpers ----------
def slugify(text: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].strip("-") or "item"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def content_hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def next_version(db: Session, module: Module) -> str:
    nums = [int(v) for v in db.scalars(select(ModuleVersion.version).where(ModuleVersion.module_id == module.id))
            if str(v).isdigit()]
    return str(max(nums, default=0) + 1)


def _int(raw, name: str, lo: int, hi: int, errors: list[str]) -> int:
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        errors.append(f"{name} must be a whole number.")
        return lo
    if not lo <= v <= hi:
        errors.append(f"{name} must be between {lo} and {hi}.")
    return v


# ---------- lessons ----------
def editor_questions(stored: list[dict]) -> list[dict]:
    """Stored quiz format -> the editor's per-option format."""
    out = []
    for q in stored:
        n = len(q["options"]["en"])
        out.append({
            "id": q["id"], "answer": q["answer"],
            "text": {lang: q["text"].get(lang, "") for lang in LANGUAGES},
            "options": [{lang: (q["options"].get(lang) or [""] * n)[i] for lang in LANGUAGES} for i in range(n)],
        })
    return out


def parse_questions(raw: list, errors: list[str]) -> list[dict]:
    """The editor's per-option format -> stored quiz format, with checks.
    English is required; another language is stored only when filled in, and then completely."""
    if not isinstance(raw, list) or not raw:
        errors.append("Add at least one question.")
        return []
    out, ids = [], set()
    for i, q in enumerate(raw, 1):
        where = f"Question {i}"
        text = {k: str(v).strip() for k, v in (q.get("text") or {}).items() if k in LANGUAGES}
        opts = [{k: str(v).strip() for k, v in o.items() if k in LANGUAGES} for o in (q.get("options") or [])]
        if not text.get("en"):
            errors.append(f"{where}: English question text is required.")
        if len(opts) < 2:
            errors.append(f"{where}: give at least 2 answer options.")
        if any(not o.get("en") for o in opts):
            errors.append(f"{where}: every answer option needs English text.")
        answer = q.get("answer")
        if not isinstance(answer, int) or not 0 <= answer < len(opts):
            errors.append(f"{where}: mark the correct answer.")
        stored_text, stored_opts = {"en": text.get("en", "")}, {"en": [o.get("en", "") for o in opts]}
        for lang in OTHER_LANGS:
            t, o = text.get(lang, ""), [x.get(lang, "") for x in opts]
            if not t and not any(o):
                continue
            if not t or not all(o):
                errors.append(f"{where}: the {LANGUAGES[lang]['name']} translation is incomplete "
                              "(fill in the question and every option, or leave it all empty).")
                continue
            stored_text[lang], stored_opts[lang] = t, o
        qid = str(q.get("id") or "").strip()
        if not re.fullmatch(r"\w{1,30}", qid) or qid in ids:
            qid = ""
        out.append({"id": qid, "text": stored_text, "options": stored_opts, "answer": answer})
        ids.add(qid)
    # new questions get ids that never clash with existing ones (ids are kept across versions)
    n = 1
    for q in out:
        if not q["id"]:
            while f"q{n}" in ids:
                n += 1
            q["id"] = f"q{n}"
            ids.add(q["id"])
    return out


def lesson_from_form(form: dict) -> tuple[dict, list[str]]:
    """Build and check the lesson content from the editor form. Returns (data, errors)."""
    errors: list[str] = []
    try:
        raw_q = json.loads(form.get("questions_json") or "[]")
    except json.JSONDecodeError:
        raw_q, errors = [], ["The question list could not be read. Reload the page and try again."]
    data = {
        "title": (form.get("title") or "").strip(),
        "summary": (form.get("summary") or "").strip(),
        "source_doc": (form.get("source_doc") or "").strip(),
        "pass_mark": _int(form.get("pass_mark", 80), "Pass mark", 1, 100, errors),
        "questions_per_attempt": _int(form.get("questions_per_attempt", 5), "Questions per attempt", 1, 100, errors),
        "max_attempts": _int(form.get("max_attempts", 3), "Maximum attempts", 1, 20, errors),
        "acknowledgment": (form.get("acknowledgment") or "").strip(),
        "questions": parse_questions(raw_q, errors),
    }
    if not data["title"]:
        errors.insert(0, "Title is required.")
    if len(data["title"]) > 200:
        errors.append("Title must be 200 characters or fewer.")
    if not data["acknowledgment"]:
        errors.append("Acknowledgment text is required.")
    if data["questions"] and data["questions_per_attempt"] > len(data["questions"]):
        errors.append(f"Questions per attempt ({data['questions_per_attempt']}) is more than the "
                      f"{len(data['questions'])} question(s) in the bank.")
    return data, errors


def lesson_data(mv: ModuleVersion) -> dict:
    """A published version in the editor's shape (used to pre-fill a revision and to detect 'no change')."""
    return {"title": mv.title.strip(), "summary": (mv.summary or "").strip(),
            "source_doc": (mv.source_doc or "").strip(), "pass_mark": mv.pass_mark,
            "questions_per_attempt": mv.questions_per_attempt, "max_attempts": mv.max_attempts,
            "acknowledgment": mv.acknowledgment_text.strip(), "questions": mv.questions}


def publish_lesson(db: Session, actor: str, data: dict, module: Module | None = None,
                   copy_videos: bool = False) -> ModuleVersion:
    """Publish `data` as a new lesson, or as the next version of `module`. Does not commit."""
    h = content_hash(data)
    previous = db.get(ModuleVersion, module.current_version_id) if module and module.current_version_id else None
    if previous is not None and content_hash(lesson_data(previous)) == h:
        raise ContentError(["Nothing was changed, so no new version was published."])
    new = module is None
    if new:
        module = Module(slug=slugify(data["title"], set(db.scalars(select(Module.slug)))), title=data["title"])
        db.add(module)
        db.flush()
    mv = ModuleVersion(
        module_id=module.id, version=next_version(db, module), title=data["title"], summary=data["summary"],
        source_doc=data["source_doc"], pass_mark=data["pass_mark"],
        questions_per_attempt=data["questions_per_attempt"], max_attempts=data["max_attempts"],
        acknowledgment_text=data["acknowledgment"], questions=data["questions"], content_hash=h)
    db.add(mv)
    db.flush()
    module.title, module.current_version_id = data["title"], mv.id
    audit.log(db, actor, "publish_version", "module_version", mv.id, {
        "slug": module.slug, "version": mv.version, "content_hash": h, "source": "admin editor",
        "previous_version_id": previous.id if previous else None, "questions": len(data["questions"])})
    if copy_videos and previous is not None:
        for v in previous.videos:
            _copy_video(db, actor, v, mv)
    return mv


def _copy_video(db: Session, actor: str, src: Video, mv: ModuleVersion) -> None:
    """Give the new version its own file (a hard link, so no extra disk space), so that later
    replacing either version's video never changes the other's."""
    rel = f"{mv.module.slug}/v{mv.version}/{src.lang}.mp4"
    source, dest = settings.media_dir / src.filename, settings.media_dir / rel
    if not source.is_file():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    try:
        os.link(source, dest)
    except OSError:
        shutil.copy2(source, dest)
    v = Video(module_version_id=mv.id, lang=src.lang, filename=rel, sha256=src.sha256,
              uploaded_by=src.uploaded_by, uploaded_at=utcnow())
    db.add(v)
    db.flush()
    audit.log(db, actor, "video_copied", "video", v.id, {
        "module_version_id": mv.id, "lang": src.lang, "file": rel, "sha256": src.sha256,
        "copied_from_video_id": src.id})


# ---------- courses ----------
def save_course(db: Session, actor: str, course: Course | None, form: dict, module_ids: list[int]) -> Course:
    """Create or update a course and its ordered lesson list. Does not commit."""
    errors: list[str] = []
    title = (form.get("title") or "").strip()
    summary = (form.get("summary") or "").strip()
    if not title:
        errors.append("Course title is required.")
    if len(title) > 200:
        errors.append("Course title must be 200 characters or fewer.")
    default_pos = (db.scalar(select(func.max(Course.position))) or 0) + 10
    position = _int(form.get("position") or default_pos, "List order", 0, 100000, errors)
    if len(set(module_ids)) != len(module_ids):
        errors.append("A lesson is listed twice in this course.")
    modules = {m.id: m for m in db.scalars(select(Module).where(Module.id.in_(module_ids)))}
    if any(i not in modules for i in module_ids):
        errors.append("One of the chosen lessons no longer exists.")
    if errors:
        raise ContentError(errors)
    new = course is None
    if new:
        course = Course(slug=slugify(title, set(db.scalars(select(Course.slug)))), title=title)
        db.add(course)
        before = None
    else:
        before = {"title": course.title, "summary": course.summary, "position": course.position,
                  "lessons": [cl.module.slug for cl in course.lessons]}
    course.title, course.summary, course.position = title, summary, position
    slugs = [modules[i].slug for i in module_ids]
    if new or before["lessons"] != slugs:
        course.lessons.clear()
        db.flush()
        for n, i in enumerate(module_ids, 1):
            course.lessons.append(CourseLesson(module_id=i, position=n))
    db.flush()
    after = {"title": title, "summary": summary, "position": position, "lessons": slugs}
    if new or before != after:
        audit.log(db, actor, "course_created" if new else "course_updated", "course", course.id,
                  {**after, "before": before} if before else after)
    return course
