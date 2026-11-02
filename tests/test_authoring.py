import json
import re

from seed import seed

ADMIN = ("boss", "pw")


def q(text, options, answer, **extra):
    """One question in the editor's format; extra = {lang: (text, [options])}."""
    t = {"en": text, **{l: v[0] for l, v in extra.items()}}
    opts = [{"en": o, **{l: v[1][i] for l, v in extra.items()}} for i, o in enumerate(options)]
    return {"id": "", "text": t, "options": opts, "answer": answer}


def lesson_form(title="Lockout Tagout", questions=None, **over):
    form = {"title": title, "summary": "Isolate energy before work.", "source_doc": "SOP-SAFE-001 v2",
            "pass_mark": "80", "questions_per_attempt": "2", "max_attempts": "3",
            "acknowledgment": "I understood this lesson.",
            "questions_json": json.dumps(questions if questions is not None else [
                q("What comes first?", ["Isolate", "Start work"], 0),
                q("Who removes a lock?", ["Anyone", "The person who fitted it"], 1,
                  ar=("من يزيل القفل؟", ["أي شخص", "الشخص الذي ركّبه"])),
            ])}
    form.update(over)
    return form


def _db():
    from app.db import SessionLocal
    return SessionLocal()


def test_import_button_is_gone(client):
    assert client.post("/admin/modules/sync", auth=ADMIN).status_code in (404, 405)
    page = client.get("/admin/modules", auth=ADMIN).text
    assert "Import content" not in page and "+ New lesson" in page and "+ New course" in page


def test_editor_pages_render(client):
    seed()
    for url in ("/admin/lessons/new", "/admin/lessons/1/revise", "/admin/courses/new", "/admin/courses/1/edit",
                "/admin/lessons/new?course_id=1"):
        assert client.get(url, auth=ADMIN).status_code == 200, url
    assert client.get("/admin/lessons/1/revise").status_code == 401


def test_create_lesson(client):
    r = client.post("/admin/lessons/save", auth=ADMIN, data=lesson_form())
    assert r.status_code == 200 and "Published Lockout Tagout v1" in r.text
    from app.models import AuditLog, Module, ModuleVersion
    with _db() as db:
        m = db.query(Module).one()
        mv = db.get(ModuleVersion, m.current_version_id)
        assert (m.slug, mv.version, mv.pass_mark, mv.questions_per_attempt) == ("lockout-tagout", "1", 80, 2)
        assert [x["id"] for x in mv.questions] == ["q1", "q2"]
        assert mv.questions[0]["text"] == {"en": "What comes first?"}  # empty languages are not stored
        assert mv.questions[1]["options"]["ar"][1] == "الشخص الذي ركّبه" and mv.questions[1]["answer"] == 1
        e = db.query(AuditLog).filter_by(action="publish_version").one()
        assert e.payload["source"] == "admin editor"
    assert "Lockout Tagout" in client.get("/admin/assign", auth=ADMIN).text


def test_lesson_validation_keeps_what_was_typed(client):
    bad = [q("Half translated?", ["Yes", "No"], 0, hi=("आधा?", ["हाँ", ""])),
           {"id": "", "text": {"en": "No answer ticked"}, "options": [{"en": "a"}, {"en": "b"}], "answer": None}]
    r = client.post("/admin/lessons/save", auth=ADMIN, data=lesson_form(questions=bad, questions_per_attempt="5"))
    assert r.status_code == 400
    assert "Question 1: the Hindi translation is incomplete" in r.text
    assert "Question 2: mark the correct answer." in r.text
    assert "Questions per attempt (5) is more than the 2 question(s)" in r.text
    assert json.dumps("आधा?")[1:-1] in r.text and 'value="Lockout Tagout"' in r.text  # nothing typed is lost
    r = client.post("/admin/lessons/save", auth=ADMIN, data=lesson_form(title="  "))
    assert r.status_code == 400 and "Title is required." in r.text
    from app.models import Module
    with _db() as db:
        assert db.query(Module).count() == 0


def test_revise_publishes_new_version_and_copies_videos(client):
    seed()
    from app.config import settings
    from app.models import AuditLog, Module, ModuleVersion, Video
    r = client.post("/admin/modules/1/video", auth=ADMIN, data={"lang": "en"},
                    files={"file": ("v.mp4", b"\x00\x00\x00\x18ftypmp42" + b"1" * 50, "video/mp4")})
    assert r.status_code == 200
    page = client.get("/admin/lessons/1/revise", auth=ADMIN).text
    assert "publishes <b>version 2</b>" in page and "Copy the current videos (en)" in page
    form = dict(re.findall(r'<input name="(\w+)"[^>]*value="([^"]*)"', page))
    with _db() as db:
        v1 = db.get(ModuleVersion, db.get(Module, 1).current_version_id)
        questions = json.loads(json.dumps(v1.questions))
        v1_ids = [x["id"] for x in questions]
    data = {"title": form["title"], "summary": v1.summary, "source_doc": v1.source_doc, "pass_mark": "70",
            "questions_per_attempt": "5", "max_attempts": "3", "acknowledgment": v1.acknowledgment_text,
            "module_id": "1", "copy_videos": "1"}
    import app.authoring as a
    editor_q = a.editor_questions(questions)
    editor_q.append(q("A new question?", ["x", "y", "z"], 2))

    # unchanged content: refused
    r = client.post("/admin/lessons/save", auth=ADMIN, data={**data, "pass_mark": str(v1.pass_mark),
                                                             "questions_json": json.dumps(a.editor_questions(questions))})
    assert r.status_code == 400 and "Nothing was changed" in r.text

    r = client.post("/admin/lessons/save", auth=ADMIN, data={**data, "questions_json": json.dumps(editor_q)})
    assert r.status_code == 200 and "v2" in r.text, r.text[:500]
    with _db() as db:
        m = db.get(Module, 1)
        v2 = db.get(ModuleVersion, m.current_version_id)
        old = db.query(ModuleVersion).filter_by(module_id=1, version="1").one()
        assert v2.version == "2" and v2.pass_mark == 70 and old.pass_mark == 80  # v1 untouched
        assert [x["id"] for x in v2.questions][:-1] == v1_ids and v2.questions[-1]["id"] not in v1_ids
        copied = db.query(Video).filter_by(module_version_id=v2.id).one()
        assert copied.filename.endswith("/v2/en.mp4")
        f1, f2 = settings.media_dir / old.videos[0].filename, settings.media_dir / copied.filename
        assert f2.read_bytes() == f1.read_bytes()
        assert db.query(AuditLog).filter_by(action="video_copied").count() == 1
    # replacing the v2 video leaves v1's file alone
    client.post(f"/admin/modules/{v2.id}/video", auth=ADMIN, data={"lang": "en"},
                files={"file": ("n.mp4", b"\x00\x00\x00\x18ftypmp42" + b"2" * 50, "video/mp4")})
    assert f1.read_bytes().endswith(b"1" * 50) and f2.read_bytes().endswith(b"2" * 50)
    assert "Chain intact" in client.get("/admin/audit", auth=ADMIN).text


def test_create_and_edit_course(client):
    for t in ("Lesson A", "Lesson B", "Lesson C"):
        client.post("/admin/lessons/save", auth=ADMIN, data=lesson_form(title=t))
    r = client.post("/admin/courses/save", auth=ADMIN, data={"title": "Safety", "summary": "", "position": "",
                                                             "lesson_ids": ["2", "1"]})
    assert r.status_code == 200 and "Saved course Safety" in r.text
    page = client.get("/admin/modules", auth=ADMIN).text
    assert page.index("Lesson 1 · Lesson B") < page.index("Lesson 2 · Lesson A")

    # duplicate lesson is refused
    r = client.post("/admin/courses/save", auth=ADMIN, data={"course_id": "1", "title": "Safety",
                                                             "lesson_ids": ["1", "1"]})
    assert r.status_code == 400 and "listed twice" in r.text

    r = client.post("/admin/courses/save", auth=ADMIN, data={"course_id": "1", "title": "Site Safety",
                                                             "position": "5", "lesson_ids": ["1", "3", "2"]})
    assert r.status_code == 200
    # a new lesson created from the course is appended as the last lesson
    r = client.post("/admin/lessons/save", auth=ADMIN, data=lesson_form(title="Lesson D", course_id="1"))
    assert "added to Site Safety" in r.text
    from app.models import AuditLog, Course
    with _db() as db:
        c = db.get(Course, 1)
        assert c.title == "Site Safety" and [cl.module.title for cl in c.lessons] == [
            "Lesson A", "Lesson C", "Lesson B", "Lesson D"]
        upd = db.query(AuditLog).filter_by(action="course_updated").order_by(AuditLog.id).all()
        assert upd[0].payload["before"]["lessons"] == ["lesson-b", "lesson-a"]

    # an empty course still shows, with its Edit button
    client.post("/admin/courses/save", auth=ADMIN, data={"title": "Machines", "lesson_ids": []})
    page = client.get("/admin/modules", auth=ADMIN).text
    assert "Course: Machines" in page and "/admin/courses/2/edit" in page
