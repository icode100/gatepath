from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["AUTO_CREATE_DB"] = "true"
os.environ["SEED_DATA"] = "true"

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
