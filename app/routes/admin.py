"""Admin / supervisor portal (HTTP Basic auth)."""
import csv
import hashlib
import io
import json
from urllib.parse import quote
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, authoring, courses
from ..certificates import build_certificate, build_course_certificate
from ..config import LANGUAGES, AdminUser, settings
from ..db import get_db
from ..models import (Acknowledgment, Assignment, AssignmentItem, AuditLog, Course, CourseCompletion, Module,
                      ModuleVersion, Trainee, Video, utcnow)
from ..security import new_token, require_admin
from ..templating import templates
from ..whatsapp import message_text, normalize_phone, wa_link

router = APIRouter(prefix="/admin")


def _go(url: str):
    return RedirectResponse(url, status_code=303)


@router.get("")
def dashboard(request: Request, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    items = db.scalars(select(AssignmentItem).join(Assignment).order_by(Assignment.created_at.desc())).all()
    counts = {s: sum(1 for i in items if i.status == s) for s in ("pending", "watched", "passed", "failed")}
    now = utcnow()
    overdue = [i for i in items if i.status in ("pending", "watched") and i.assignment.due_date
               and i.assignment.due_date.replace(tzinfo=i.assignment.due_date.tzinfo or timezone.utc) < now]
    return templates.TemplateResponse(request, "admin/dashboard.html", {
        "user": user, "items": items, "counts": counts, "overdue": overdue})


# ---------- trainees ----------
@router.get("/trainees")
def trainees(request: Request, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(Trainee).order_by(Trainee.name)).all()
    return templates.TemplateResponse(request, "admin/trainees.html", {
        "user": user, "trainees": rows, "languages": LANGUAGES, "msg": request.query_params.get("msg")})


def _upsert_trainee(db: Session, actor: str, employee_id: str, name: str, phone: str, role: str) -> str:
    # Language is not set here: each trainee picks it on their own link (trainee.py: choose_language).
    employee_id, name = employee_id.strip(), name.strip()
    if not employee_id or not name or not normalize_phone(phone):
        return f"skipped incomplete row ({employee_id or name or '?'})"
    t = db.scalar(select(Trainee).where(Trainee.employee_id == employee_id))
    data = {"name": name, "phone": normalize_phone(phone), "role": role.strip() or "Technician"}
    if t:
        for k, v in data.items():
            setattr(t, k, v)
        audit.log(db, actor, "trainee_updated", "trainee", t.id, data)
        return f"updated {employee_id}"
    t = Trainee(employee_id=employee_id, **data)
    db.add(t)
    db.flush()
    audit.log(db, actor, "trainee_created", "trainee", t.id, {"employee_id": employee_id, **data})
    return f"added {employee_id}"


@router.post("/trainees")
def add_trainee(employee_id: str = Form(...), name: str = Form(...), phone: str = Form(...),
                role: str = Form("Technician"),
                user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    msg = _upsert_trainee(db, user.username, employee_id, name, phone, role)
    db.commit()
    return _go(f"/admin/trainees?msg={msg}")


@router.post("/trainees/import")
async def import_trainees(file: UploadFile = File(...), user: AdminUser = Depends(require_admin),
                          db: Session = Depends(get_db)):
    text = (await file.read()).decode("utf-8-sig")
    results = [_upsert_trainee(db, user.username, r.get("employee_id", ""), r.get("name", ""),
                               r.get("phone", ""), r.get("role", ""))
               for r in csv.DictReader(io.StringIO(text))]
    db.commit()
    return _go(f"/admin/trainees?msg=Import: {len(results)} rows ({sum('added' in r for r in results)} added, "
               f"{sum('updated' in r for r in results)} updated, {sum('skipped' in r for r in results)} skipped)")


@router.post("/trainees/{tid}/toggle")
def toggle_trainee(tid: int, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    t = db.get(Trainee, tid) or _404()
    t.active = not t.active
    audit.log(db, user.username, "trainee_active" if t.active else "trainee_inactive", "trainee", t.id)
    db.commit()
    return _go("/admin/trainees")


def _404():
    raise HTTPException(404)


# ---------- modules & videos ----------
@router.get("/modules")
def modules(request: Request, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    catalog = courses.assign_catalog(db)
    shown = {c.id for c, _ in catalog if c}
    empty = [(c, []) for c in db.scalars(select(Course).where(Course.active).order_by(Course.position, Course.title))
             if c.id not in shown]  # new courses with no lessons yet still need an Edit button
    catalog = sorted([g for g in catalog if g[0]] + empty, key=lambda g: (g[0].position, g[0].title)) + \
        [g for g in catalog if not g[0]]
    return templates.TemplateResponse(request, "admin/modules.html", {
        "user": user, "catalog": catalog, "languages": LANGUAGES, "msg": request.query_params.get("msg")})


def _lesson_editor(request: Request, user: AdminUser, db: Session, *, module: Module | None, data: dict,
                   course_id: int | None = None, copy_videos: bool = True, errors: list[str] | None = None,
                   questions: list | None = None):
    current = db.get(ModuleVersion, module.current_version_id) if module and module.current_version_id else None
    return templates.TemplateResponse(request, "admin/lesson_edit.html", {
        "user": user, "module": module, "current": current, "data": data,
        "questions": questions if questions is not None else authoring.editor_questions(data.get("questions") or []),
        "languages": LANGUAGES, "course": db.get(Course, course_id) if course_id else None,
        "copy_videos": copy_videos, "errors": errors or [],
        "next_version": authoring.next_version(db, module) if module else "1",
    }, status_code=400 if errors else 200)


@router.get("/lessons/new")
def new_lesson(request: Request, course_id: int | None = None, user: AdminUser = Depends(require_admin),
               db: Session = Depends(get_db)):
    data = {"title": "", "summary": "", "source_doc": "", "pass_mark": 80, "questions_per_attempt": 5,
            "max_attempts": 3, "acknowledgment": authoring.DEFAULT_ACK, "questions": []}
    return _lesson_editor(request, user, db, module=None, data=data, course_id=course_id)


@router.get("/lessons/{module_id}/revise")
def revise_lesson(module_id: int, request: Request, user: AdminUser = Depends(require_admin),
                  db: Session = Depends(get_db)):
    module = db.get(Module, module_id) or _404()
    mv = db.get(ModuleVersion, module.current_version_id) or _404()
    return _lesson_editor(request, user, db, module=module, data=authoring.lesson_data(mv))


@router.post("/lessons/save")
async def save_lesson(request: Request, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    form = dict(await request.form())
    module = db.get(Module, int(form["module_id"])) or _404() if form.get("module_id") else None
    course = db.get(Course, int(form["course_id"])) or _404() if form.get("course_id") and not module else None
    copy_videos = form.get("copy_videos") == "1"
    data, errors = authoring.lesson_from_form(form)
    if not errors:
        try:
            mv = authoring.publish_lesson(db, user.username, data, module, copy_videos=copy_videos)
        except authoring.ContentError as e:
            errors = e.errors
    if errors:
        db.rollback()
        try:  # show exactly what was typed, including unfinished translations
            typed = json.loads(form.get("questions_json") or "[]")
        except json.JSONDecodeError:
            typed = []
        return _lesson_editor(request, user, db, module=module, data=data, questions=typed if isinstance(typed, list) else [],
                              course_id=course.id if course else None, copy_videos=copy_videos, errors=errors)
    if course is not None:  # new lesson added from a course: append it as the last lesson
        authoring.save_course(db, user.username, course, {"title": course.title, "summary": course.summary,
                              "position": course.position},
                              [cl.module_id for cl in course.lessons] + [mv.module_id])
    db.commit()
    where = f" (added to {course.title})" if course else ""
    return _go("/admin/modules?msg=" + quote(f"Published {mv.title} v{mv.version}{where}"))


def _course_editor(request: Request, user: AdminUser, db: Session, *, course: Course | None, form: dict,
                   lesson_ids: list[int], errors: list[str] | None = None):
    lessons = []
    for m in db.scalars(select(Module).where(Module.current_version_id.is_not(None)).order_by(Module.title)):
        lessons.append({"id": m.id, "title": m.title, "version": db.get(ModuleVersion, m.current_version_id).version})
    return templates.TemplateResponse(request, "admin/course_edit.html", {
        "user": user, "course": course, "form": form, "lesson_ids": lesson_ids, "lessons": lessons,
        "errors": errors or []}, status_code=400 if errors else 200)


@router.get("/courses/new")
def new_course(request: Request, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    return _course_editor(request, user, db, course=None, form={}, lesson_ids=[])


@router.get("/courses/{course_id}/edit")
def edit_course(course_id: int, request: Request, user: AdminUser = Depends(require_admin),
                db: Session = Depends(get_db)):
    c = db.get(Course, course_id) or _404()
    return _course_editor(request, user, db, course=c, lesson_ids=[cl.module_id for cl in c.lessons],
                          form={"title": c.title, "summary": c.summary, "position": c.position})


@router.post("/courses/save")
async def save_course(request: Request, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    raw = await request.form()
    form = {k: raw.get(k) for k in ("title", "summary", "position")}
    course = db.get(Course, int(raw["course_id"])) or _404() if raw.get("course_id") else None
    lesson_ids = [int(x) for x in raw.getlist("lesson_ids") if x]
    try:
        course = authoring.save_course(db, user.username, course, form, lesson_ids)
    except authoring.ContentError as e:
        db.rollback()
        return _course_editor(request, user, db, course=course, form=form, lesson_ids=lesson_ids, errors=e.errors)
    db.commit()
    return _go("/admin/modules?msg=" + quote(f"Saved course {course.title}"))


@router.post("/modules/{mv_id}/video")
async def upload_video(mv_id: int, lang: str = Form(...), file: UploadFile = File(...),
                       user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    mv = db.get(ModuleVersion, mv_id) or _404()
    if lang not in LANGUAGES:
        raise HTTPException(400, "Unknown language")
    if not (file.filename or "").lower().endswith(".mp4"):
        raise HTTPException(400, "Upload an .mp4 file")
    rel = f"{mv.module.slug}/v{mv.version}/{lang}.mp4"
    dest = settings.media_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    tmp = dest.with_suffix(".part")
    with tmp.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            h.update(chunk)
            out.write(chunk)
    tmp.replace(dest)
    v = db.scalar(select(Video).where(Video.module_version_id == mv.id, Video.lang == lang))
    action = "video_replaced" if v else "video_uploaded"
    if not v:
        v = Video(module_version_id=mv.id, lang=lang)
        db.add(v)
    v.filename, v.sha256, v.uploaded_by, v.uploaded_at = rel, h.hexdigest(), user.username, utcnow()
    db.flush()
    audit.log(db, user.username, action, "video", v.id,
              {"module_version_id": mv.id, "lang": lang, "file": rel, "sha256": v.sha256})
    db.commit()
    return _go(f"/admin/modules?msg={action.replace('_', ' ')}: {rel}")


# ---------- assignments ----------
@router.get("/assign")
def assign_form(request: Request, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    people = db.scalars(select(Trainee).where(Trainee.active).order_by(Trainee.name)).all()
    return templates.TemplateResponse(request, "admin/assign.html", {
        "user": user, "trainees": people, "catalog": courses.assign_catalog(db), "languages": LANGUAGES})


@router.post("/assign")
async def assign(request: Request, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    form = await request.form()
    trainee_ids = [int(x) for x in form.getlist("trainee_ids")]
    mv_ids = list(dict.fromkeys(int(x) for x in form.getlist("module_version_ids")))
    order = courses.lesson_order_key(db)
    mv_ids.sort(key=lambda i: order(db.get(ModuleVersion, i) or _404()))
    if not trainee_ids or not mv_ids:
        raise HTTPException(400, "Select at least one trainee and one module.")
    due = None
    if form.get("due_date"):
        due = datetime.combine(datetime.fromisoformat(str(form["due_date"])).date(), time(23, 59), timezone.utc)
    expires = max(utcnow() + timedelta(days=settings.assignment_valid_days), (due or utcnow()) + timedelta(days=7))
    created = []
    for tid in trainee_ids:
        t = db.get(Trainee, tid) or _404()
        done = set(db.scalars(select(AssignmentItem.module_version_id).join(Assignment).where(
            Assignment.trainee_id == t.id, AssignmentItem.status == "passed")))
        todo = [m for m in mv_ids if m not in done]
        if not todo:
            continue
        a = Assignment(token=new_token(), trainee_id=t.id, created_by=user.username, due_date=due, expires_at=expires)
        db.add(a)
        db.flush()
        for m in todo:
            db.add(AssignmentItem(assignment_id=a.id, module_version_id=m))
        audit.log(db, user.username, "assigned", "assignment", a.id, {
            "trainee": t.employee_id, "module_version_ids": todo,
            "skipped_already_passed": sorted(set(mv_ids) & done), "due": due})
        created.append(a.id)
    db.commit()
    if not created:
        return _go("/admin/assignments?ids=none&msg=No links created: the selected trainees have already "
                   "passed these module versions.")
    return _go("/admin/assignments?ids=" + ",".join(map(str, created)))


def _wa(a: Assignment) -> str:
    titles = [f"{i.module_version.title} (v{i.module_version.version})" for i in a.items]
    due = a.due_date.strftime("%d/%m/%Y") if a.due_date else None
    return wa_link(a.trainee.phone, message_text(a.trainee.name, titles, f"{settings.base_url}/t/{a.token}", due))


@router.get("/assignments")
def assignments(request: Request, ids: str = "", msg: str | None = None, user: AdminUser = Depends(require_admin),
                db: Session = Depends(get_db)):
    q = select(Assignment).order_by(Assignment.created_at.desc())
    only = [int(x) for x in ids.split(",") if x.isdigit()]
    if ids:
        q = q.where(Assignment.id.in_(only))
    rows = db.scalars(q.limit(300)).all()
    return templates.TemplateResponse(request, "admin/assignments.html", {
        "user": user, "rows": [(a, _wa(a)) for a in rows], "filtered": bool(ids), "msg": msg, "base_url": settings.base_url})


@router.post("/assignments/{aid}/sent")
def mark_sent(aid: int, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    a = db.get(Assignment, aid) or _404()
    a.sent_at = utcnow()
    audit.log(db, user.username, "whatsapp_opened", "assignment", a.id, {"phone": a.trainee.phone})
    db.commit()
    return {"ok": True}


# ---------- records ----------
@router.get("/records")
def records(request: Request, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    acks = db.scalars(select(Acknowledgment).order_by(Acknowledgment.at.desc())).all()
    completions = db.scalars(select(CourseCompletion).order_by(CourseCompletion.completed_at.desc())).all()
    idx = courses.lesson_index(db)
    course_of = {a.id: (idx.get(a.item.module_version.module_id) or (None,))[0] for a in acks}
    return templates.TemplateResponse(request, "admin/records.html", {
        "user": user, "acks": acks, "completions": completions, "course_of": course_of})


@router.get("/courses/{cc_id}/certificate.pdf")
def admin_course_certificate(cc_id: int, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    cc = db.get(CourseCompletion, cc_id) or _404()
    return Response(build_course_certificate(cc), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{cc.certificate_no}.pdf"'})


@router.post("/records/{ack_id}/signoff")
def signoff(ack_id: int, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    ack = db.get(Acknowledgment, ack_id) or _404()
    if not ack.supervisor_name:
        ack.supervisor_name, ack.supervisor_at = user.display_name, utcnow()
        audit.log(db, user.username, "supervisor_signoff", "acknowledgment", ack.id,
                  {"supervisor": user.display_name, "certificate_no": ack.certificate_no})
        db.commit()
    return _go("/admin/records")


@router.get("/records/{ack_id}/certificate.pdf")
def admin_certificate(ack_id: int, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    ack = db.get(Acknowledgment, ack_id) or _404()
    return Response(build_certificate(ack), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{ack.certificate_no}.pdf"'})


@router.get("/records.csv")
def records_csv(user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    idx = courses.lesson_index(db)
    w.writerow(["certificate_no", "employee_id", "name", "role", "course", "lesson_no", "lesson", "lesson_version",
                "source_doc",
                "language", "score_pct", "pass_mark", "attempt_no", "acknowledged_at_utc", "typed_name",
                "supervisor", "supervisor_at_utc"])
    for a in db.scalars(select(Acknowledgment).order_by(Acknowledgment.at)):
        mv, t = a.item.module_version, a.item.assignment.trainee
        c = idx.get(mv.module_id)
        w.writerow([a.certificate_no, t.employee_id, t.name, t.role, c[0].title if c else "", c[1] if c else "",
                    mv.title, mv.version, mv.source_doc,
                    a.attempt.lang, a.attempt.score_pct, mv.pass_mark, a.attempt.attempt_no,
                    a.at.isoformat(), a.typed_name, a.supervisor_name or "",
                    a.supervisor_at.isoformat() if a.supervisor_at else ""])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="training_records.csv"'})


@router.get("/audit")
def audit_view(request: Request, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    ok, n, bad = audit.verify_chain(db)
    recent = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(200)).all()
    return templates.TemplateResponse(request, "admin/audit.html", {
        "user": user, "ok": ok, "n": n, "bad": bad, "recent": recent})
