from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend
from sqlalchemy.ext.asyncio import AsyncEngine

from app.storage.db import make_engine, migrate


class MemoryKeyring(KeyringBackend):  # type: ignore[misc]
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.store.pop((service, username), None)


@pytest.fixture(autouse=True)
def app_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("NEURALRADAR_HOME", str(home))
    return home


@pytest.fixture(autouse=True)
def memory_keyring() -> Iterator[MemoryKeyring]:
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def no_real_embedding_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test không bao giờ tải model fastembed thật."""
    from tests.helpers import FakeEmbedder

    monkeypatch.setattr("app.pipeline.process.FastEmbedder", lambda *_a, **_k: FakeEmbedder())


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    db_path = tmp_path / "test.db"
    migrate(db_path)
    eng = make_engine(db_path)
    yield eng
    await eng.dispose()
