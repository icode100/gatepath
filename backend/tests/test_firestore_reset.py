from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any

import pytest

import app.user_state.firestore as firestore_module
from app.user_state.firestore import FirestoreUserStateRepository
from app.user_state.repository import UserStateUnavailable


class _Snapshot:
    def __init__(self, reference: _Document, data: dict[str, Any] | None) -> None:
        self.reference = reference
        self.exists = data is not None
        self._data = copy.deepcopy(data)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._data or {})


class _Document:
    def __init__(self, client: _Client, collection_name: str, document_id: str) -> None:
        self._client = client
        self._collection_name = collection_name
        self.id = document_id

    async def get(self, *, transaction: Any | None = None) -> _Snapshot:
        del transaction
        data = self._client.data.setdefault(self._collection_name, {}).get(self.id)
        return _Snapshot(self, data)


class _Query:
    def __init__(
        self,
        collection: _Collection,
        field: str,
        value: Any,
    ) -> None:
        self._collection = collection
        self._field = field
        self._value = value
        self._limit: int | None = None

    def limit(self, count: int) -> _Query:
        self._limit = count
        return self

    async def stream(self):
        records = [
            (document_id, data)
            for document_id, data in self._collection._records.items()
            if data.get(self._field) == self._value
        ]
        if self._limit is not None:
            records = records[: self._limit]
        for document_id, data in records:
            reference = self._collection.document(document_id)
            yield _Snapshot(reference, data)


class _Collection:
    def __init__(self, client: _Client, name: str) -> None:
        self._client = client
        self._name = name

    @property
    def _records(self) -> dict[str, dict[str, Any]]:
        return self._client.data.setdefault(self._name, {})

    def document(self, document_id: str) -> _Document:
        return _Document(self._client, self._name, document_id)

    def where(self, field: str, operator: str, value: Any) -> _Query:
        assert operator == "=="
        return _Query(self, field, value)


class _Transaction:
    def __init__(self, client: _Client) -> None:
        self._client = client

    def create(self, reference: _Document, data: dict[str, Any]) -> None:
        records = self._client.data.setdefault(reference._collection_name, {})
        if reference.id in records:
            raise RuntimeError("Document already exists")
        records[reference.id] = copy.deepcopy(data)

    def delete(self, reference: _Document) -> None:
        self._client.data.setdefault(reference._collection_name, {}).pop(
            reference.id,
            None,
        )

    def set(self, reference: _Document, data: dict[str, Any]) -> None:
        self._client.data.setdefault(reference._collection_name, {})[
            reference.id
        ] = copy.deepcopy(data)


class _Batch:
    def __init__(self, client: _Client) -> None:
        self._client = client
        self._deletes: list[_Document] = []

    def delete(self, reference: _Document) -> None:
        self._deletes.append(reference)

    async def commit(self) -> None:
        self._client.batch_commit_count += 1
        if self._client.fail_batch_commit == self._client.batch_commit_count:
            raise RuntimeError("Injected batch failure")
        for reference in self._deletes:
            self._client.data.setdefault(reference._collection_name, {}).pop(
                reference.id,
                None,
            )


class _Client:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict[str, Any]]] = {}
        self.batch_commit_count = 0
        self.fail_batch_commit: int | None = None

    def collection(self, name: str) -> _Collection:
        return _Collection(self, name)

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    def batch(self) -> _Batch:
        return _Batch(self)


@pytest.fixture
def direct_transactional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        firestore_module,
        "import_module",
        lambda _: SimpleNamespace(async_transactional=lambda function: function),
    )


@pytest.mark.asyncio
async def test_firestore_records_archive_practice_once_without_scored_attempt(
    direct_transactional: None,
) -> None:
    del direct_transactional
    client = _Client()
    prefix = "archive_progress_test"
    owner = "fb-v1-archive-owner"
    repository = FirestoreUserStateRepository(
        client=client,
        collection_prefix=prefix,
    )

    first = await repository.record_archive_practice(owner, 101)
    duplicate = await repository.record_archive_practice(owner, 101)
    second = await repository.record_archive_practice(owner, 202)

    assert first.archive_practiced_ids == duplicate.archive_practiced_ids == (101,)
    assert second.archive_practiced_ids == (101, 202)
    assert second.total_attempts == second.total_responses == 0
    stored = client.data[f"{prefix}_progress"][owner]
    assert stored["archive_practiced_ids"] == [101, 202]


@pytest.mark.asyncio
async def test_firestore_reset_resumes_across_batch_boundary(
    direct_transactional: None,
) -> None:
    del direct_transactional
    client = _Client()
    prefix = "reset_test"
    owner = "fb-v1-reset-owner"
    other = "fb-v1-other-owner"
    client.data[f"{prefix}_sessions"] = {
        **{
            f"session-{index}": {"user_key": owner}
            for index in range(405)
        },
        "other-session": {"user_key": other},
    }
    client.data[f"{prefix}_attempts"] = {
        **{
            f"attempt-{index}": {"user_key": owner}
            for index in range(401)
        },
        "other-attempt": {"user_key": other},
    }
    client.data[f"{prefix}_progress"] = {
        owner: {"user_key": owner},
        other: {"user_key": other},
    }
    client.fail_batch_commit = 2
    repository = FirestoreUserStateRepository(
        client=client,
        collection_prefix=prefix,
    )

    with pytest.raises(UserStateUnavailable, match="Progress reset is unavailable"):
        await repository.reset_progress(owner)

    assert owner in client.data[f"{prefix}_resets"]
    assert sum(
        item["user_key"] == owner
        for item in client.data[f"{prefix}_sessions"].values()
    ) == 5
    assert len(client.data[f"{prefix}_attempts"]) == 402

    client.fail_batch_commit = None
    resumed = await repository.reset_progress(owner)

    assert resumed.sessions_deleted == 5
    assert resumed.attempts_deleted == 401
    assert resumed.progress_deleted is True
    assert client.data[f"{prefix}_sessions"] == {
        "other-session": {"user_key": other}
    }
    assert client.data[f"{prefix}_attempts"] == {
        "other-attempt": {"user_key": other}
    }
    assert client.data[f"{prefix}_progress"] == {
        other: {"user_key": other}
    }
    assert client.data[f"{prefix}_resets"] == {}


@pytest.mark.asyncio
async def test_firestore_reset_waits_for_target_guest_claim(
    direct_transactional: None,
) -> None:
    del direct_transactional
    client = _Client()
    prefix = "claim_barrier_test"
    owner = "fb-v1-claim-target"
    client.data[f"{prefix}_sessions"] = {
        "target-session": {"user_key": owner}
    }
    client.data[f"{prefix}_progress"] = {owner: {"user_key": owner}}
    client.data[f"{prefix}_claim_targets"] = {
        owner: {
            "guest_user_key": "anon-source",
            "target_user_key": owner,
            "status": "claiming",
        }
    }
    repository = FirestoreUserStateRepository(
        client=client,
        collection_prefix=prefix,
    )

    with pytest.raises(UserStateUnavailable, match="Progress claim is in progress"):
        await repository.reset_progress(owner)

    assert client.data[f"{prefix}_sessions"] == {
        "target-session": {"user_key": owner}
    }
    assert owner in client.data[f"{prefix}_progress"]
    assert client.data.get(f"{prefix}_resets", {}) == {}
