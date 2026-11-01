"""Trainee flow: personal link -> confirm Employee ID -> pick module ->
choose language & watch -> quiz -> acknowledgment -> certificate."""
import random
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..certificates import build_certificate
from ..config import LANGUAGES, settings
from ..db import get_db
from ..models import Acknowledgment, Assignment, AssignmentItem, QuizAttempt, Video, ViewEvent, utcnow
from ..security import client_ip
from ..templating import templates

router = APIRouter(prefix="/t")


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt


def _assignment(db: Session, token: str) -> Assignment:
    a = db.scalar(select(Assignment).where(Assignment.token == token))
    if not a or not a.trainee.active:
        raise HTTPException(404, "This training link is not valid.")
    return a


def _expired(a: Assignment) -> bool:
    return _aware(a.expires_at) < utcnow()


def _verified(request: Request, a: Assignment) -> bool:
    return request.session.get("assignment_id") == a.id


def _item(db: Session, request: Request, token: str, item_id: int) -> AssignmentItem:
    a = _assignment(db, token)
    if not _verified(request, a):
        raise HTTPException(403, "Please open your training link and confirm your Employee ID.")
    if _expired(a):
        raise HTTPException(410, "This training link has expired. Ask your supervisor for a new one.")
    item = db.get(AssignmentItem, item_id)
    if not item or item.assignment_id != a.id:
        raise HTTPException(404)
    return item


def _videos(item: AssignmentItem) -> dict[str, Video]:
    return {v.lang: v for v in item.module_version.videos}


def _questions_by_id(item: AssignmentItem) -> dict:
    return {q["id"]: q for q in item.module_version.questions}


def _localize(q: dict, lang: str) -> dict:
    use = lang if lang in q["text"] and lang in q["options"] else "en"
    return {"id": q["id"], "text": q["text"][use], "options": q["options"][use], "lang": use}


@router.get("/{token}")
def landing(token: str, request: Request, db: Session = Depends(get_db)):
    a = _assignment(db, token)
    if _expired(a):
        return templates.TemplateResponse(request, "trainee/message.html",
                                          {"title": "Link expired", "msg": "Ask your supervisor for a new link."})
    if not _verified(request, a):
        return templates.TemplateResponse(request, "trainee/verify.html", {"a": a, "error": None})
    if request.session.get("lang") not in LANGUAGES:
        return _language_page(request, a)
    return templates.TemplateResponse(request, "trainee/modules.html", {
        "a": a, "languages": LANGUAGES, "lang": request.session["lang"]})


def _language_page(request: Request, a: Assignment):
    current = request.session.get("lang") or a.trainee.preferred_lang
    return templates.TemplateResponse(request, "trainee/language.html", {
        "a": a, "languages": LANGUAGES, "current": current})


@router.get("/{token}/language")
def language_form(token: str, request: Request, db: Session = Depends(get_db)):
    a = _assignment(db, token)
    if not _verified(request, a):
        return RedirectResponse(f"/t/{token}", status_code=303)
    return _language_page(request, a)


@router.post("/{token}/language")
def choose_language(token: str, request: Request, lang: str = Form(...), db: Session = Depends(get_db)):
    """The trainee picks their own language; it is remembered for their next visit."""
    a = _assignment(db, token)
    if not _verified(request, a):
        return RedirectResponse(f"/t/{token}", status_code=303)
    if lang not in LANGUAGES:
        raise HTTPException(400, "Unknown language")
    request.session["lang"] = lang
    trainee = a.trainee
    if trainee.preferred_lang != lang:
        audit.log(db, trainee.employee_id, "language_chosen", "trainee", trainee.id,
                  {"from": trainee.preferred_lang, "to": lang})
        trainee.preferred_lang = lang
        db.commit()
    return RedirectResponse(f"/t/{token}", status_code=303)


@router.post("/{token}")
def verify(token: str, request: Request, employee_id: str = Form(...), db: Session = Depends(get_db)):
    a = _assignment(db, token)
    fails = request.session.get("verify_fails", 0)
    if fails >= 5:
        return templates.TemplateResponse(request, "trainee/message.html", {
            "title": "Too many attempts", "msg": "Contact your supervisor."}, status_code=429)
    if employee_id.strip().casefold() != a.trainee.employee_id.casefold():
        request.session["verify_fails"] = fails + 1
        audit.log(db, f"link:{a.id}", "verify_failed", "assignment", a.id, {"ip": client_ip(request)})
        db.commit()
        return templates.TemplateResponse(request, "trainee/verify.html",
                                          {"a": a, "error": "Employee ID does not match this link."}, status_code=400)
    request.session.clear()
    request.session["assignment_id"] = a.id
    audit.log(db, a.trainee.employee_id, "verified", "assignment", a.id,
              {"ip": client_ip(request), "ua": request.headers.get("user-agent", "")[:200]})
    db.commit()
    return RedirectResponse(f"/t/{token}", status_code=303)


@router.get("/{token}/m/{item_id}")
def watch(token: str, item_id: int, request: Request, lang: str | None = None, db: Session = Depends(get_db)):
    item = _item(db, request, token, item_id)
    vids = _videos(item)
    chosen = request.session.get("lang") or item.assignment.trainee.preferred_lang
    if lang not in vids:
        lang = next((c for c in (chosen, "en") if c in vids), next(iter(vids), None))
    if lang:
        db.add(ViewEvent(item_id=item.id, lang=lang, event="open"))
        db.commit()
    return templates.TemplateResponse(request, "trainee/watch.html", {
        "token": token, "item": item, "lang": lang, "videos": vids, "languages": LANGUAGES,
        "chosen": chosen, "missing_chosen": bool(vids) and chosen not in vids})


class EventIn(BaseModel):
    lang: str
    event: str
    position: float = 0


@router.post("/{token}/m/{item_id}/event")
def video_event(token: str, item_id: int, ev: EventIn, request: Request, db: Session = Depends(get_db)):
    item = _item(db, request, token, item_id)
    if ev.event not in ("play", "ended") or ev.lang not in LANGUAGES:
        raise HTTPException(400)
    db.add(ViewEvent(item_id=item.id, lang=ev.lang, event=ev.event, position_s=int(ev.position)))
    if ev.event == "ended" and item.status == "pending":
        item.status = "watched"
    db.commit()
    return {"ok": True}


@router.get("/{token}/video/{item_id}/{lang}")
def video_file(token: str, item_id: int, lang: str, request: Request, db: Session = Depends(get_db)):
    item = _item(db, request, token, item_id)
    v = _videos(item).get(lang)
    path = settings.media_dir / v.filename if v else None
    if not path or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="video/mp4")


def _open_attempt(item: AssignmentItem) -> QuizAttempt | None:
    return next((t for t in item.attempts if t.submitted_at is None), None)


@router.get("/{token}/m/{item_id}/quiz")
def quiz(token: str, item_id: int, request: Request, lang: str = "en", db: Session = Depends(get_db)):
    item = _item(db, request, token, item_id)
    mv = item.module_version
    if item.status == "passed":
        return RedirectResponse(f"/t/{token}/m/{item_id}/done", status_code=303)
    if item.status == "failed":
        return templates.TemplateResponse(request, "trainee/message.html", {
            "title": "No attempts left", "msg": "Contact your supervisor for re-training."})
    passed_unacked = next((t for t in item.attempts if t.passed), None)
    if passed_unacked:
        return RedirectResponse(f"/t/{token}/m/{item_id}/ack", status_code=303)
    if db.scalar(select(ViewEvent.id).where(ViewEvent.item_id == item.id).limit(1)) is None:
        return RedirectResponse(f"/t/{token}/m/{item_id}", status_code=303)
    attempt = _open_attempt(item)
    if attempt is None:  # same questions on refresh: no re-rolling to find easier ones
        lang = lang if lang in LANGUAGES else "en"
        ids = random.sample([q["id"] for q in mv.questions], mv.questions_per_attempt)
        attempt = QuizAttempt(item_id=item.id, attempt_no=len(item.attempts) + 1, lang=lang, question_ids=ids)
        db.add(attempt)
        audit.log(db, item.assignment.trainee.employee_id, "quiz_started", "assignment_item", item.id,
                  {"attempt_no": attempt.attempt_no, "question_ids": ids, "lang": lang})
        db.commit()
    by_id = _questions_by_id(item)
    qs = [_localize(by_id[qid], attempt.lang) for qid in attempt.question_ids]
    return templates.TemplateResponse(request, "trainee/quiz.html", {
        "token": token, "item": item, "attempt": attempt, "questions": qs,
        "dir": LANGUAGES[attempt.lang]["dir"]})


@router.post("/{token}/m/{item_id}/quiz")
async def submit_quiz(token: str, item_id: int, request: Request, db: Session = Depends(get_db)):
    item = _item(db, request, token, item_id)
    attempt = _open_attempt(item)
    if attempt is None:
        return RedirectResponse(f"/t/{token}/m/{item_id}/quiz", status_code=303)
    form = await request.form()
    by_id = _questions_by_id(item)
    answers, correct = {}, 0
    for qid in attempt.question_ids:
        raw = form.get(f"q_{qid}")
        if raw is None or not str(raw).isdigit():
            qs = [_localize(by_id[i], attempt.lang) for i in attempt.question_ids]
            return templates.TemplateResponse(request, "trainee/quiz.html", {
                "token": token, "item": item, "attempt": attempt, "questions": qs,
                "dir": LANGUAGES[attempt.lang]["dir"], "error": "Please answer every question."}, status_code=400)
        answers[qid] = int(raw)
        correct += int(raw) == by_id[qid]["answer"]
    mv = item.module_version
    attempt.answers = answers
    attempt.score_pct = round(100 * correct / len(attempt.question_ids))
    attempt.passed = attempt.score_pct >= mv.pass_mark
    attempt.submitted_at = utcnow()
    if not attempt.passed and attempt.attempt_no >= mv.max_attempts:
        item.status = "failed"
    audit.log(db, item.assignment.trainee.employee_id, "quiz_submitted", "quiz_attempt", attempt.id, {
        "item_id": item.id, "attempt_no": attempt.attempt_no, "answers": answers,
        "score_pct": attempt.score_pct, "passed": attempt.passed})
    db.commit()
    if attempt.passed:
        return RedirectResponse(f"/t/{token}/m/{item_id}/ack", status_code=303)
    return templates.TemplateResponse(request, "trainee/result.html", {
        "token": token, "item": item, "attempt": attempt,
        "left": mv.max_attempts - attempt.attempt_no})


@router.get("/{token}/m/{item_id}/ack")
def ack_form(token: str, item_id: int, request: Request, db: Session = Depends(get_db)):
    item = _item(db, request, token, item_id)
    if item.acknowledgment:
        return RedirectResponse(f"/t/{token}/m/{item_id}/done", status_code=303)
    if not any(t.passed for t in item.attempts):
        return RedirectResponse(f"/t/{token}/m/{item_id}/quiz", status_code=303)
    return templates.TemplateResponse(request, "trainee/ack.html", {"token": token, "item": item, "error": None})


@router.post("/{token}/m/{item_id}/ack")
def ack_submit(token: str, item_id: int, request: Request, typed_name: str = Form(""),
               agree: str | None = Form(None), db: Session = Depends(get_db)):
    item = _item(db, request, token, item_id)
    if item.acknowledgment:
        return RedirectResponse(f"/t/{token}/m/{item_id}/done", status_code=303)
    passed = next((t for t in item.attempts if t.passed), None)
    if not passed:
        return RedirectResponse(f"/t/{token}/m/{item_id}/quiz", status_code=303)
    if not agree or len(typed_name.strip()) < 3:
        return templates.TemplateResponse(request, "trainee/ack.html", {
            "token": token, "item": item,
            "error": "Tick the box and type your full name to sign."}, status_code=400)
    now = utcnow()
    trainee = item.assignment.trainee
    ack = Acknowledgment(
        item_id=item.id, attempt_id=passed.id, statement=item.module_version.acknowledgment_text,
        typed_name=typed_name.strip()[:200], employee_id=trainee.employee_id, ip=client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:400], at=now,
        certificate_no=f"TRN-{now:%Y%m%d}-{item.id:06d}")
    db.add(ack)
    item.status, item.completed_at = "passed", now
    db.flush()
    audit.log(db, trainee.employee_id, "acknowledged", "acknowledgment", ack.id, {
        "item_id": item.id, "module_version_id": item.module_version_id, "typed_name": ack.typed_name,
        "certificate_no": ack.certificate_no, "statement": ack.statement, "ip": ack.ip})
    db.commit()
    return RedirectResponse(f"/t/{token}/m/{item_id}/done", status_code=303)


@router.get("/{token}/m/{item_id}/done")
def done(token: str, item_id: int, request: Request, db: Session = Depends(get_db)):
    item = _item(db, request, token, item_id)
    if not item.acknowledgment:
        return RedirectResponse(f"/t/{token}/m/{item_id}/quiz", status_code=303)
    return templates.TemplateResponse(request, "trainee/done.html", {"token": token, "item": item})


@router.get("/{token}/m/{item_id}/certificate.pdf")
def certificate(token: str, item_id: int, request: Request, db: Session = Depends(get_db)):
    item = _item(db, request, token, item_id)
    if not item.acknowledgment:
        raise HTTPException(404)
    return Response(build_certificate(item.acknowledgment), media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{item.acknowledgment.certificate_no}.pdf"'})
