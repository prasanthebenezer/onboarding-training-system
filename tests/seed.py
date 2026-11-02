"""Test data: the Plant Technology lessons kept in content/ (the original YAML
sources), published through the same code the admin editor uses."""
from pathlib import Path

import yaml

CONTENT = Path(__file__).resolve().parent.parent / "content"
KEYS = ("title", "summary", "source_doc", "pass_mark", "questions_per_attempt", "max_attempts", "acknowledgment")


def seed():
    from app import authoring
    from app.db import SessionLocal
    from app.models import Module
    with SessionLocal() as db:
        by_slug = {}
        for path in sorted(CONTENT.glob("modules/*/module.yaml")):
            y = yaml.safe_load(path.read_text(encoding="utf-8"))
            data = {k: y.get(k, "") for k in KEYS}
            data = {**data, "pass_mark": int(y.get("pass_mark", 80)), "max_attempts": int(y.get("max_attempts", 3)),
                    "questions_per_attempt": int(y.get("questions_per_attempt", 5)),
                    "acknowledgment": y["acknowledgment"].strip(), "summary": (y.get("summary") or "").strip(),
                    "questions": y["questions"]}
            mv = authoring.publish_lesson(db, "seed", data)
            db.flush()
            m = db.get(Module, mv.module_id)
            m.slug = y["slug"]  # keep the familiar slugs the tests refer to
            by_slug[y["slug"]] = m.id
        for path in sorted(CONTENT.glob("courses/*/course.yaml")):
            c = yaml.safe_load(path.read_text(encoding="utf-8"))
            authoring.save_course(db, "seed", None, {"title": c["title"], "summary": c.get("summary", ""),
                                                     "position": c.get("position", 10)},
                                  [by_slug[s] for s in c["lessons"]])
        db.commit()
