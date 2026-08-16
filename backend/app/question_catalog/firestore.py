from __future__ import annotations

import asyncio
import hashlib
import json
import os
from importlib import import_module
from time import monotonic
from typing import Any, Mapping

from app import firebase_auth
from app.config import settings
from app.models import Difficulty, QuestionSource, QuestionType, SessionMode
from app.question_catalog.domain import (
    CatalogQuestion,
    CatalogSnapshot,
    CatalogSubject,
    CatalogTestForm,
    CatalogTopic,
    QuestionCatalogInvalid,
    QuestionCatalogUnavailable,
)


MAX_RUNTIME_SHARD_BYTES = 600 * 1024


class FirestoreQuestionCatalogRepository:
    """Read an immutable catalog release from Firestore into a bounded cache.

    The runtime projection is packed into checksum-bound immutable shard
    documents. Loading those shards once per instance avoids both a combinatorial
    Firestore index matrix and thousands of document reads per serverless cold
    start. ``gatepath_catalog_meta/current`` is written last by the migration
    publisher and acts as the atomic release pointer.
    """

    def __init__(
        self,
        *,
        client: Any | None = None,
        collection_prefix: str | None = None,
        database_id: str | None = None,
        cache_seconds: int | None = None,
    ) -> None:
        self._client = client
        self._client_lock = asyncio.Lock()
        self._snapshot_lock = asyncio.Lock()
        self._collection_prefix = (
            collection_prefix or settings.firestore_collection_prefix
        ).strip()
        self._database_id = (database_id or settings.firestore_database_id).strip()
        self._cache_seconds = (
            cache_seconds
            if cache_seconds is not None
            else settings.firestore_catalog_cache_seconds
        )
        self._cached_snapshot: CatalogSnapshot | None = None
        self._cache_deadline = 0.0

    def _collection_name(self, suffix: str) -> str:
        return f"{self._collection_prefix}_{suffix}"

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is not None:
                return self._client
            if settings.question_catalog_configuration_issues:
                raise QuestionCatalogUnavailable(
                    "Firestore question catalog is not configured"
                )
            try:
                if os.environ.get("FIRESTORE_EMULATOR_HOST", "").strip():
                    firestore_v1 = import_module("google.cloud.firestore_v1")
                    google_credentials = import_module("google.auth.credentials")
                    self._client = firestore_v1.AsyncClient(
                        project=settings.firebase_project_id.strip(),
                        database=self._database_id,
                        credentials=google_credentials.AnonymousCredentials(),
                    )
                else:
                    firestore_async = import_module("firebase_admin.firestore_async")
                    app = firebase_auth.get_firebase_admin_app()
                    self._client = firestore_async.client(
                        app=app,
                        database_id=self._database_id,
                    )
            except Exception as exc:
                raise QuestionCatalogUnavailable(
                    "Firestore question catalog is unavailable"
                ) from exc
            return self._client

    async def _metadata(self, client: Any) -> dict[str, Any]:
        try:
            snapshot = await client.collection(
                self._collection_name("catalog_meta")
            ).document("current").get()
        except Exception as exc:
            raise QuestionCatalogUnavailable(
                "Firestore catalog metadata is unavailable"
            ) from exc
        if not snapshot.exists:
            raise QuestionCatalogUnavailable("Firestore catalog is not published")
        document = snapshot.to_dict()
        if not isinstance(document, dict):
            raise QuestionCatalogInvalid("Firestore catalog metadata is invalid")
        return document

    @staticmethod
    def _release_id(metadata: Mapping[str, Any]) -> str:
        for field_name in ("release_id", "catalog_version", "checksum"):
            value = metadata.get(field_name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        raise QuestionCatalogInvalid("Firestore catalog metadata has no release identity")

    @staticmethod
    def _canonical_json_bytes(value: Any) -> bytes:
        try:
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise QuestionCatalogInvalid(
                "Firestore catalog contains non-canonical JSON values"
            ) from exc
        return encoded.encode("utf-8")

    async def _release_manifest(
        self,
        client: Any,
        release_id: str,
    ) -> tuple[Any, dict[str, Any]]:
        reference = client.collection(
            self._collection_name("catalog_releases")
        ).document(release_id)
        try:
            snapshot = await reference.get()
        except Exception as exc:
            raise QuestionCatalogUnavailable(
                "Firestore catalog release manifest is unavailable"
            ) from exc
        if not snapshot.exists:
            raise QuestionCatalogUnavailable(
                "Firestore catalog release is not published"
            )
        document = snapshot.to_dict()
        if not isinstance(document, dict):
            raise QuestionCatalogInvalid("Firestore catalog release is invalid")
        if (
            document.get("release_id") != release_id
            or document.get("status") != "ready"
            or document.get("immutable") is not True
        ):
            raise QuestionCatalogInvalid(
                "Firestore catalog release is not immutable and ready"
            )
        root_payload = {
            "release_id": document.get("release_id"),
            "source_bindings": document.get("source_bindings"),
            "counts": document.get("counts"),
            "collections": document.get("collections"),
            "shards": document.get("shards"),
        }
        calculated_root = hashlib.sha256(
            self._canonical_json_bytes(root_payload)
        ).hexdigest()
        if document.get("manifest_root_sha256") != calculated_root:
            raise QuestionCatalogInvalid(
                "Firestore catalog release root checksum does not match"
            )
        return reference, document

    async def _runtime_shards(
        self,
        client: Any,
        release_reference: Any,
        manifest: Mapping[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        descriptors = manifest.get("shards")
        if not isinstance(descriptors, list) or not all(
            isinstance(item, dict) for item in descriptors
        ):
            raise QuestionCatalogInvalid("Firestore shard manifest is invalid")
        required_kinds = {
            "subjects",
            "topics",
            "revision_notes",
            "questions",
            "question_index",
            "question_aliases",
            "test_forms",
        }
        selected: list[tuple[str, dict[str, Any], Any]] = []
        seen_ids: set[str] = set()
        seen_kinds: set[str] = set()
        for descriptor in descriptors:
            kind = descriptor.get("kind")
            index = descriptor.get("index")
            if kind not in required_kinds:
                continue
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise QuestionCatalogInvalid("Firestore shard index is invalid")
            shard_id = f"{kind}--{index:03d}"
            if shard_id in seen_ids:
                raise QuestionCatalogInvalid("Firestore shard manifest has duplicates")
            seen_ids.add(shard_id)
            seen_kinds.add(kind)
            selected.append(
                (
                    shard_id,
                    descriptor,
                    release_reference.collection("shards").document(shard_id),
                )
            )
        missing_kinds = required_kinds.difference(seen_kinds)
        if missing_kinds:
            raise QuestionCatalogInvalid(
                "Firestore catalog is missing runtime shard kinds: "
                + ", ".join(sorted(missing_kinds))
            )
        try:
            snapshots = {
                snapshot.id: snapshot
                async for snapshot in client.get_all(
                    [reference for _, _, reference in selected]
                )
            }
        except Exception as exc:
            raise QuestionCatalogUnavailable(
                "Firestore catalog shards are unavailable"
            ) from exc
        if set(snapshots) != seen_ids or any(
            not snapshot.exists for snapshot in snapshots.values()
        ):
            raise QuestionCatalogUnavailable(
                "One or more Firestore catalog shards are missing"
            )

        by_kind = {kind: [] for kind in required_kinds}
        release_id = manifest.get("release_id")
        catalog_version = manifest.get("catalog_version")
        for shard_id, descriptor, _ in selected:
            document = snapshots[shard_id].to_dict()
            if not isinstance(document, dict):
                raise QuestionCatalogInvalid(f"Firestore shard {shard_id} is invalid")
            kind = descriptor["kind"]
            index = descriptor["index"]
            items = document.get("items")
            if not isinstance(items, list) or not all(
                isinstance(item, dict) for item in items
            ):
                raise QuestionCatalogInvalid(
                    f"Firestore shard {shard_id} payload is invalid"
                )
            encoded = self._canonical_json_bytes(items)
            payload_sha256 = hashlib.sha256(encoded).hexdigest()
            if (
                document.get("release_id") != release_id
                or document.get("catalog_version") != catalog_version
                or document.get("kind") != kind
                or document.get("index") != index
                or document.get("count") != len(items)
                or document.get("encoded_bytes") != len(encoded)
                or document.get("payload_sha256") != payload_sha256
                or descriptor.get("count") != len(items)
                or descriptor.get("payload_sha256") != payload_sha256
                or descriptor.get("encoded_bytes") != len(encoded)
                or len(encoded) > MAX_RUNTIME_SHARD_BYTES
            ):
                raise QuestionCatalogInvalid(
                    f"Firestore shard {shard_id} failed integrity validation"
                )
            by_kind[kind].extend(items)
        return by_kind

    async def _load_consistent_snapshot(self, client: Any) -> CatalogSnapshot:
        for _ in range(2):
            metadata_before = await self._metadata(client)
            release_id = self._release_id(metadata_before)
            release_reference, manifest = await self._release_manifest(
                client,
                release_id,
            )
            manifest_root = manifest.get("manifest_root_sha256")
            if metadata_before.get("checksum") != manifest_root:
                raise QuestionCatalogInvalid(
                    "Firestore catalog pointer checksum does not match its release"
                )
            descriptors = manifest.get("shards")
            if (
                not isinstance(descriptors, list)
                or metadata_before.get("shard_count") != len(descriptors)
            ):
                raise QuestionCatalogInvalid(
                    "Firestore catalog pointer shard count does not match its release"
                )
            shards = await self._runtime_shards(
                client,
                release_reference,
                manifest,
            )
            metadata_after = await self._metadata(client)
            if (
                self._release_id(metadata_after) != release_id
                or metadata_after.get("checksum") != manifest_root
            ):
                continue
            counts = manifest.get("counts")
            if not isinstance(counts, dict):
                raise QuestionCatalogInvalid("Firestore catalog counts are invalid")
            runtime_metadata = dict(metadata_after)
            runtime_metadata.update(counts)
            runtime_metadata["manifest_root_sha256"] = manifest_root
            return CatalogSnapshot.build(
                release_id=release_id,
                metadata=runtime_metadata,
                subject_documents=shards["subjects"],
                topic_documents=shards["topics"],
                note_documents=shards["revision_notes"],
                question_documents=shards["questions"],
                question_index_documents=shards["question_index"],
                question_alias_documents=shards["question_aliases"],
                test_form_documents=shards["test_forms"],
            )
        raise QuestionCatalogUnavailable(
            "Firestore catalog changed while it was being loaded"
        )

    async def snapshot(self, *, force_refresh: bool = False) -> CatalogSnapshot:
        now = monotonic()
        if (
            not force_refresh
            and self._cached_snapshot is not None
            and now < self._cache_deadline
        ):
            return self._cached_snapshot
        async with self._snapshot_lock:
            now = monotonic()
            if (
                not force_refresh
                and self._cached_snapshot is not None
                and now < self._cache_deadline
            ):
                return self._cached_snapshot
            client = await self._get_client()
            metadata = await self._metadata(client)
            release_id = self._release_id(metadata)
            if (
                not force_refresh
                and self._cached_snapshot is not None
                and self._cached_snapshot.release_id == release_id
            ):
                self._cache_deadline = monotonic() + self._cache_seconds
                return self._cached_snapshot
            loaded = await self._load_consistent_snapshot(client)
            self._cached_snapshot = loaded
            self._cache_deadline = monotonic() + self._cache_seconds
            return loaded

    async def healthcheck(self) -> None:
        await self.snapshot()

    async def find_subject(
        self,
        *,
        subject_id: int | None = None,
        subject_slug: str | None = None,
    ) -> CatalogSubject | None:
        current = await self.snapshot()
        if subject_id is not None:
            return current.subjects_by_id.get(subject_id)
        if subject_slug is not None:
            return current.subjects_by_slug.get(subject_slug)
        return None

    async def find_topic(self, topic_id: int) -> CatalogTopic | None:
        return (await self.snapshot()).topics_by_id.get(topic_id)

    async def find_question(
        self,
        question_id: int,
        *,
        active_only: bool = True,
    ) -> CatalogQuestion | None:
        question = (await self.snapshot()).question_for_runtime_id(question_id)
        if question is None or (active_only and not question.is_active):
            return None
        return question

    async def questions_by_ids(
        self,
        question_ids: list[int] | tuple[int, ...],
    ) -> list[CatalogQuestion]:
        current = await self.snapshot()
        resolved: list[CatalogQuestion] = []
        for item in question_ids:
            question = current.question_for_runtime_id(item, preserve_alias=True)
            if question is not None:
                resolved.append(question)
        return resolved

    async def filter_questions(
        self,
        *,
        subject_id: int | None = None,
        topic_id: int | None = None,
        source: QuestionSource | None = None,
        source_kind: QuestionSource | None = None,
        year: int | None = None,
        question_type: QuestionType | None = None,
        question_types: tuple[QuestionType, ...] | None = None,
        difficulty: Difficulty | None = None,
        difficulties: tuple[Difficulty, ...] | None = None,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[CatalogQuestion], int]:
        questions = (await self.snapshot()).active_questions
        search_term = search.strip().casefold() if search and search.strip() else None
        filtered = [
            item
            for item in questions
            if (subject_id is None or item.subject_id == subject_id)
            and (topic_id is None or item.topic_id == topic_id)
            and (source is None or item.source == source)
            and (source_kind is None or item.source_kind == source_kind)
            and (year is None or item.year == year)
            and (question_type is None or item.question_type == question_type)
            and (question_types is None or item.question_type in question_types)
            and (difficulty is None or item.difficulty == difficulty)
            and (difficulties is None or item.difficulty in difficulties)
            and (search_term is None or search_term in item.search_text)
        ]
        total = len(filtered)
        if limit is None:
            return filtered[offset:], total
        return filtered[offset : offset + limit], total

    async def list_test_forms(
        self,
        *,
        mode: SessionMode | None = None,
        subject_id: int | None = None,
    ) -> list[CatalogTestForm]:
        forms = [
            item
            for item in (await self.snapshot()).test_forms
            if (mode is None or item.mode == mode)
            and (subject_id is None or item.subject_id == subject_id)
        ]
        forms.sort(
            key=lambda item: (
                0 if item.mode == SessionMode.FULL else 1,
                item.subject.order_index if item.subject else 0,
                item.form_number,
            )
        )
        return forms

    async def find_test_form(self, catalog_id: str) -> CatalogTestForm | None:
        return (await self.snapshot()).test_forms_by_id.get(catalog_id)
