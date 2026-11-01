import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'test.db'}"
    os.environ["MEDIA_DIR"] = str(tmp_path / "media")
    os.environ["CONTENT_DIR"] = str(ROOT / "content")
    os.environ["ADMIN_USERS"] = "boss:pw:Boss Person"
    os.environ["BASE_URL"] = "http://testserver"
    for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[m]
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c
