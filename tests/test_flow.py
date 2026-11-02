import re
from urllib.parse import unquote

ADMIN = ("boss", "pw")


def _setup(client):
    r = client.post("/admin/modules/sync", auth=ADMIN)
    assert r.status_code == 200 and "Published / updated: pt-01-raw-materials v1" in r.text, r.text
    from app.db import SessionLocal
    from app.models import ModuleVersion
    with SessionLocal() as db:
        mv = db.query(ModuleVersion).filter_by(version="1").order_by(ModuleVersion.id).first()
        mv_id, answers = mv.id, {q["id"]: q["answer"] for q in mv.questions}
    r = client.post(f"/admin/modules/{mv_id}/video", auth=ADMIN, data={"lang": "ar"},
                    files={"file": ("a.mp4", b"\x00\x00\x00\x18ftypmp42" + b"0" * 100, "video/mp4")})
    assert r.status_code == 200
    client.post("/admin/trainees", auth=ADMIN, data={
        "employee_id": "E100", "name": "Test Tech", "phone": "+966 50 123 4567", "role": "Technician",
        "preferred_lang": "ar"})
    r = client.post("/admin/assign", auth=ADMIN, data={"trainee_ids": ["1"], "module_version_ids": [str(mv_id)]})
    assert r.status_code == 200
    wa = re.search(r'href="(https://wa\.me/[^"]+)"', r.text).group(1)
    assert wa.startswith("https://wa.me/966501234567?text=")
    token = re.search(r"/t/([A-Za-z0-9_-]+)", unquote(wa)).group(1)
    return token, answers


def test_admin_requires_auth(client):
    assert client.get("/admin").status_code == 401
    assert client.get("/admin", auth=("boss", "wrong")).status_code == 401


def test_full_trainee_flow(client):
    token, answers = _setup(client)
    assert "Employee ID" in client.get(f"/t/{token}").text
    assert client.post(f"/t/{token}", data={"employee_id": "WRONG"}).status_code == 400
    assert client.get(f"/t/{token}/m/1/quiz").status_code == 403
    client.post(f"/t/{token}", data={"employee_id": "e100"})
    page = client.get(f"/t/{token}/m/1").text
    assert "العربية" in page
    v = client.get(f"/t/{token}/video/1/ar", headers={"Range": "bytes=0-9"})
    assert v.status_code in (200, 206)
    assert client.post(f"/t/{token}/m/1/event", json={"lang": "ar", "event": "ended", "position": 120}).json()["ok"]

    # attempt 1: all wrong
    q = client.get(f"/t/{token}/m/1/quiz?lang=en").text
    qids = re.findall(r'name="q_(\w+)" value="0"', q)
    assert len(qids) == 5
    assert client.get(f"/t/{token}/m/1/quiz").text.count('value="0"') == 5  # same questions on refresh
    r = client.post(f"/t/{token}/m/1/quiz", data={f"q_{i}": (answers[i] + 1) % 4 for i in qids})
    assert "Score: 0%" in r.text and "2 attempt(s) left" in r.text

    # attempt 2: all right
    q = client.get(f"/t/{token}/m/1/quiz").text
    qids = re.findall(r'name="q_(\w+)" value="0"', q)
    r = client.post(f"/t/{token}/m/1/quiz", data={f"q_{i}": answers[i] for i in qids})
    assert "Training acknowledgment" in r.text
    assert client.post(f"/t/{token}/m/1/ack", data={"typed_name": "Test Tech"}).status_code == 400
    r = client.post(f"/t/{token}/m/1/ack", data={"typed_name": "Test Tech", "agree": "1"})
    assert "Lesson completed" in r.text
    pdf = client.get(f"/t/{token}/m/1/certificate.pdf")
    assert pdf.content.startswith(b"%PDF")

    r = client.post("/admin/records/1/signoff", auth=ADMIN)
    assert "Boss Person" in r.text
    csv_text = client.get("/admin/records.csv", auth=ADMIN).text
    assert "E100" in csv_text and "Boss Person" in csv_text and ",100," in csv_text
    assert "Chain intact" in client.get("/admin/audit", auth=ADMIN).text

    # re-assigning a passed module is skipped
    r = client.post("/admin/assign", auth=ADMIN, data={"trainee_ids": ["1"], "module_version_ids": ["1"]})
    assert "No links." in r.text


def test_attempts_exhausted(client):
    token, answers = _setup(client)
    client.post(f"/t/{token}", data={"employee_id": "E100"})
    client.get(f"/t/{token}/m/1")
    for _ in range(3):
        qids = re.findall(r'name="q_(\w+)" value="0"', client.get(f"/t/{token}/m/1/quiz").text)
        r = client.post(f"/t/{token}/m/1/quiz", data={f"q_{i}": (answers[i] + 1) % 4 for i in qids})
    assert "No attempts left" in r.text
    assert "No attempts left" in client.get(f"/t/{token}/m/1/quiz").text


def test_tamper_detected(client):
    _setup(client)
    from app.db import SessionLocal
    from app.models import AuditLog
    with SessionLocal() as db:
        e = db.get(AuditLog, 2)
        e.payload = {**e.payload, "forged": True}
        db.commit()
    assert "Chain broken at entry #2" in client.get("/admin/audit", auth=ADMIN).text


def test_frozen_version(client, tmp_path, monkeypatch):
    client.post("/admin/modules/sync", auth=ADMIN)
    from app import content_loader
    from app.config import settings
    import shutil
    src = settings.content_dir
    dst = tmp_path / "content"
    shutil.copytree(src, dst)
    y = dst / "modules/pt-01-raw-materials/module.yaml"
    y.write_text(y.read_text().replace("pass_mark: 80", "pass_mark: 70"))
    monkeypatch.setattr(settings, "content_dir", dst)
    from app.db import SessionLocal
    with SessionLocal() as db:
        rep = content_loader.sync(db, "t")
    assert any("version not bumped" in e for e in rep.errors)


def test_trainee_chooses_language(client):
    token, _ = _setup(client)  # module 1 has only an Arabic video uploaded
    client.post(f"/t/{token}", data={"employee_id": "E100"})

    page = client.get(f"/t/{token}").text  # first visit: language screen before the module list
    assert "Choose your language" in page and "മലയാളം" in page
    assert client.post(f"/t/{token}/language", data={"lang": "xx"}).status_code == 400

    r = client.post(f"/t/{token}/language", data={"lang": "ml"})
    assert "My training" in r.text and "മലയാളം" in r.text
    from app.db import SessionLocal
    from app.models import AuditLog, Trainee
    with SessionLocal() as db:
        assert db.query(Trainee).filter_by(employee_id="E100").one().preferred_lang == "ml"
        assert db.query(AuditLog).filter_by(action="language_chosen").count() == 1

    # no Malayalam video yet: falls back and says so
    w = client.get(f"/t/{token}/m/1").text
    assert "not available in മലയാളം yet" in w and "/video/1/ar" in w

    # chooses Arabic: plays Arabic, no notice; quiz link carries the language
    client.post(f"/t/{token}/language", data={"lang": "ar"})
    w = client.get(f"/t/{token}/m/1").text
    assert "not available" not in w and "/video/1/ar" in w and "quiz?lang=ar" in w

    # the choice is remembered on the next visit (new session)
    client.cookies.clear()
    client.post(f"/t/{token}", data={"employee_id": "E100"})
    assert 'value="ar" class="btn "' in client.get(f"/t/{token}").text


def test_admin_has_no_language_field(client):
    page = client.get("/admin/trainees", auth=ADMIN).text
    assert 'name="preferred_lang"' not in page
    r = client.post("/admin/trainees/import", auth=ADMIN, files={"file": (
        "t.csv", b"employee_id,name,phone,role,preferred_lang\nE7,Old Format,+966500000007,Technician,hi\n", "text/csv")})
    assert "1 added" in r.text  # old CSVs with a language column still import; the column is ignored


def _pass_lesson(client, token, item_id, answers):
    client.get(f"/t/{token}/m/{item_id}")
    q = client.get(f"/t/{token}/m/{item_id}/quiz").text
    qids = re.findall(r'name="q_(\w+)" value="0"', q)
    r = client.post(f"/t/{token}/m/{item_id}/quiz", data={f"q_{i}": answers[i] for i in qids})
    assert "Training acknowledgment" in r.text, r.text[:300]
    return client.post(f"/t/{token}/m/{item_id}/ack", data={"typed_name": "Test Tech", "agree": "1"})


def test_course_order_lock_and_certificate(client):
    client.post("/admin/modules/sync", auth=ADMIN)
    from app.db import SessionLocal
    from app.models import AssignmentItem, CourseCompletion, Module, ModuleVersion
    with SessionLocal() as db:
        mvs = {m.slug: db.get(ModuleVersion, m.current_version_id) for m in db.query(Module)}
        answers = {q["id"]: q["answer"] for mv in mvs.values() for q in mv.questions}
        ids = {slug: mv.id for slug, mv in mvs.items()}
    for mv_id in ids.values():
        client.post(f"/admin/modules/{mv_id}/video", auth=ADMIN, data={"lang": "en"},
                    files={"file": ("v.mp4", b"\x00\x00\x00\x18ftypmp42" + b"0" * 50, "video/mp4")})
    assert "Course: Plant Technology" in client.get("/admin/modules", auth=ADMIN).text
    page = client.get("/admin/assign", auth=ADMIN).text
    assert 'class="course-all"' in page and "Lesson 4 · Plant Technology 4" in page
    client.post("/admin/trainees", auth=ADMIN, data={"employee_id": "E9", "name": "Course Tech",
                                                     "phone": "+966500000009", "role": "Technician"})
    # submitted out of order on purpose: items must still be created in lesson order
    order = ["pt-03-main-processes", "pt-01-raw-materials", "pt-04-secondary-services", "pt-02-plant-configurations"]
    r = client.post("/admin/assign", auth=ADMIN, data={"trainee_ids": ["1"], "module_version_ids": [str(ids[s]) for s in order]})
    token = re.search(r"/t/([A-Za-z0-9_-]+)", unquote(re.search(r'href="(https://wa\.me/[^"]+)"', r.text).group(1))).group(1)
    with SessionLocal() as db:
        items = {db.get(ModuleVersion, i.module_version_id).module.slug: i.id for i in db.query(AssignmentItem)}
    assert sorted(items.values()) == [items[s] for s in sorted(items)]  # ids follow lesson order

    client.post(f"/t/{token}", data={"employee_id": "E9"})
    client.post(f"/t/{token}/language", data={"lang": "en"})
    home = client.get(f"/t/{token}").text
    assert "Plant Technology" in home and "Lesson 1 of 4" in home and home.count("🔒 Locked") == 3

    # lesson 2 is locked: every lesson page bounces back to the list with a notice
    for path in ("", "/quiz", "/ack"):
        r = client.get(f"/t/{token}/m/{items['pt-02-plant-configurations']}{path}")
        assert "Finish “Plant Technology 1: Raw Material Composition” first." in r.text

    r = _pass_lesson(client, token, items["pt-01-raw-materials"], answers)
    assert "Start next lesson" in r.text and "Plant Technology 2" in r.text
    assert client.get(f"/t/{token}").text.count("🔒 Locked") == 2
    for s in order[3:] + ["pt-03-main-processes"]:
        r = _pass_lesson(client, token, items[s], answers)
        assert "Course completed" not in r.text
    r = _pass_lesson(client, token, items["pt-04-secondary-services"], answers)
    assert "Course completed: Plant Technology" in r.text

    with SessionLocal() as db:
        cc = db.query(CourseCompletion).one()
        assert [l["position"] for l in sorted(cc.lessons, key=lambda l: l["position"])] == [1, 2, 3, 4]
        cc_id, cc_no = cc.id, cc.certificate_no
    pdf = client.get(f"/t/{token}/course/{cc_id}/certificate.pdf")
    assert pdf.content.startswith(b"%PDF")
    rec = client.get("/admin/records", auth=ADMIN).text
    assert cc_no in rec and client.get(f"/admin/courses/{cc_id}/certificate.pdf", auth=ADMIN).content.startswith(b"%PDF")
    csv_text = client.get("/admin/records.csv", auth=ADMIN).text
    assert "course,lesson_no,lesson" in csv_text.splitlines()[0] and "Plant Technology,4," in csv_text

    # a second trainee gets only lesson 4 as a refresher: not locked by lessons that weren't assigned
    client.post("/admin/trainees", auth=ADMIN, data={"employee_id": "E10", "name": "Refresher Tech",
                                                     "phone": "+966500000010", "role": "Technician"})
    r = client.post("/admin/assign", auth=ADMIN, data={"trainee_ids": ["2"], "module_version_ids": [str(ids["pt-04-secondary-services"])]})
    t2 = re.search(r"/t/([A-Za-z0-9_-]+)", unquote(re.search(r'href="(https://wa\.me/[^"]+)"', r.text).group(1))).group(1)
    client.cookies.clear()
    client.post(f"/t/{t2}", data={"employee_id": "E10"})
    client.post(f"/t/{t2}/language", data={"lang": "en"})
    home = client.get(f"/t/{t2}").text
    assert "🔒" not in home and "Start ▶" in home
