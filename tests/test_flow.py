import re
from urllib.parse import unquote

ADMIN = ("boss", "pw")


def _setup(client):
    r = client.post("/admin/modules/sync", auth=ADMIN)
    assert r.status_code == 200 and "Published: pt-01-raw-materials v1" in r.text, r.text
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
    assert "Training completed" in r.text
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
