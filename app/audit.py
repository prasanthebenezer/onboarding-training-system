"""Hash-chained audit log.

Each entry stores sha256(prev_hash + canonical JSON of the entry). Changing,
deleting or reordering any past entry breaks the chain, which verify_chain()
reports. This is tamper-evidence, not tamper-proofing: keep regular off-server
backups of the database (see docs/DEPLOY.md).
"""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditLog

GENESIS = "0" * 64


def _digest(prev_hash: str, at: datetime, actor: str, action: str, entity: str,
            entity_id: str, payload: dict) -> str:
    if at.tzinfo is None:  # SQLite drops tzinfo on read; values are stored as UTC
        at = at.replace(tzinfo=timezone.utc)
    body = json.dumps(
        {"at": at.isoformat(), "actor": actor, "action": action, "entity": entity,
         "entity_id": entity_id, "payload": payload},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


def log(db: Session, actor: str, action: str, entity: str, entity_id, payload: dict | None = None) -> AuditLog:
    last = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()).limit(1).with_for_update())
    prev = last.hash if last else GENESIS
    at = datetime.now(timezone.utc).replace(microsecond=0)
    payload = json.loads(json.dumps(payload or {}, default=str))
    entry = AuditLog(
        at=at, actor=actor, action=action, entity=entity, entity_id=str(entity_id),
        payload=payload, prev_hash=prev,
        hash=_digest(prev, at, actor, action, entity, str(entity_id), payload),
    )
    db.add(entry)
    db.flush()
    return entry


def verify_chain(db: Session) -> tuple[bool, int, int | None]:
    """Returns (ok, entries_checked, first_bad_id)."""
    prev = GENESIS
    n = 0
    for e in db.scalars(select(AuditLog).order_by(AuditLog.id)):
        n += 1
        if e.prev_hash != prev or e.hash != _digest(prev, e.at, e.actor, e.action, e.entity, e.entity_id, e.payload):
            return False, n, e.id
        prev = e.hash
    return True, n, None
