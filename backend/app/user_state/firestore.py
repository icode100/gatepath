from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from importlib import import_module
from typing import Any

from app import firebase_auth
from app.config import settings
from app.user_state.codec import (
    attempt_from_document,
    attempt_to_document,
    progress_from_document,
    progress_to_document,
    session_from_document,
    session_to_document,
)
from app.user_state.domain import (
    ProgressProjection,
    StudyAttempt,
    StudySession,
    apply_attempt_to_projection,
    empty_progress_projection,
    mark_archive_practiced,
    merge_progress_projections,
)
from app.user_state.repository import (
    UserStateAlreadySubmitted,
    UserStateError,
    UserStateNotFound,
    UserStateResetSummary,
    UserStateUnavailable,
)


FIRESTORE_BATCH_WRITE_LIMIT = 400


def _validate_document_id(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized or "/" in normalized or len(normalized.encode("utf-8")) > 512:
        raise UserStateNotFound(f"{label} not found")
    return normalized


class FirestoreUserStateRepository:
    """Firebase Admin-only user state stored in top-level collections."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        collection_prefix: str | None = None,
        database_id: str | None = None,
    ) -> None:
        self._client = client
        self._client_lock = asyncio.Lock()
        self._collection_prefix = (
            collection_prefix or settings.firestore_collection_prefix
        ).strip()
        self._database_id = (
            database_id or settings.firestore_database_id
        ).strip()
        self._sessions_name = f"{self._collection_prefix}_sessions"
        self._attempts_name = f"{self._collection_prefix}_attempts"
        self._progress_name = f"{self._collection_prefix}_progress"
        self._claims_name = f"{self._collection_prefix}_claims"
        self._claim_targets_name = f"{self._collection_prefix}_claim_targets"
        self._resets_name = f"{self._collection_prefix}_resets"

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is not None:
                return self._client
            if settings.firestore_configuration_issues:
                raise UserStateUnavailable("Firestore user state is not configured")
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
                raise UserStateUnavailable(
                    "Firestore user state is unavailable"
                ) from exc
            return self._client

    async def _query_by_owner(
        self,
        collection: Any,
        user_key: str,
    ) -> list[Any]:
        snapshots: list[Any] = []
        query = collection.where("user_key", "==", user_key)
        async for snapshot in query.stream():
            snapshots.append(snapshot)
        return snapshots

    async def create_session(self, session: StudySession) -> StudySession:
        _validate_document_id(session.id, "Study session")
        document = session_to_document(session)
        try:
            client = await self._get_client()
            reference = client.collection(self._sessions_name).document(session.id)
            claim_ref = (
                client.collection(self._claims_name).document(session.user_key)
                if session.user_key.startswith("anon-")
                else None
            )
            reset_ref = client.collection(self._resets_name).document(
                session.user_key
            )
            transaction = client.transaction()
            transactional = import_module(
                "google.cloud.firestore_v1"
            ).async_transactional

            @transactional
            async def create_in_transaction(transaction: Any) -> StudySession:
                reset_snapshot = await reset_ref.get(transaction=transaction)
                claim_snapshot = (
                    await claim_ref.get(transaction=transaction)
                    if claim_ref is not None
                    else None
                )
                existing_snapshot = await reference.get(transaction=transaction)
                if reset_snapshot.exists:
                    raise UserStateUnavailable("Progress reset is in progress")
                if claim_snapshot is not None and claim_snapshot.exists:
                    raise UserStateNotFound("User state is no longer available")
                if existing_snapshot.exists:
                    existing = session_from_document(existing_snapshot.to_dict())
                    if existing.user_key == session.user_key and existing == session:
                        return existing
                    raise UserStateAlreadySubmitted("Study session already exists")
                transaction.create(reference, document)
                return session

            return await create_in_transaction(transaction)
        except UserStateError:
            raise
        except Exception as exc:
            raise UserStateUnavailable(
                "Study session storage is unavailable"
            ) from exc

    async def get_session(
        self,
        user_key: str,
        session_id: str,
    ) -> StudySession:
        session_id = _validate_document_id(session_id, "Study session")
        try:
            client = await self._get_client()
            snapshot = await client.collection(self._sessions_name).document(
                session_id
            ).get()
            if not snapshot.exists:
                raise UserStateNotFound("Study session not found")
            session = session_from_document(snapshot.to_dict())
            if session.user_key != user_key:
                raise UserStateNotFound("Study session not found")
            return session
        except UserStateError:
            raise
        except Exception as exc:
            raise UserStateUnavailable(
                "Study session storage is unavailable"
            ) from exc

    async def submit_attempt(
        self,
        user_key: str,
        session_id: str,
        candidate_attempt: StudyAttempt,
    ) -> StudyAttempt:
        session_id = _validate_document_id(session_id, "Study session")
        _validate_document_id(candidate_attempt.id, "Study attempt")
        if (
            candidate_attempt.user_key != user_key
            or candidate_attempt.session_id != session_id
        ):
            raise UserStateNotFound("Study session not found")
        candidate_document = attempt_to_document(candidate_attempt)
        try:
            client = await self._get_client()
            transactional = import_module(
                "google.cloud.firestore_v1"
            ).async_transactional
            session_ref = client.collection(self._sessions_name).document(session_id)
            candidate_ref = client.collection(self._attempts_name).document(
                candidate_attempt.id
            )
            progress_ref = client.collection(self._progress_name).document(user_key)
            claim_ref = (
                client.collection(self._claims_name).document(user_key)
                if user_key.startswith("anon-")
                else None
            )
            reset_ref = client.collection(self._resets_name).document(user_key)
            transaction = client.transaction()

            @transactional
            async def commit_attempt(transaction: Any) -> StudyAttempt:
                reset_snapshot = await reset_ref.get(transaction=transaction)
                claim_snapshot = (
                    await claim_ref.get(transaction=transaction)
                    if claim_ref is not None
                    else None
                )
                session_snapshot = await session_ref.get(transaction=transaction)
                if reset_snapshot.exists:
                    raise UserStateUnavailable("Progress reset is in progress")
                if claim_snapshot is not None and claim_snapshot.exists:
                    raise UserStateNotFound("User state is no longer available")
                if not session_snapshot.exists:
                    raise UserStateNotFound("Study session not found")
                session = session_from_document(session_snapshot.to_dict())
                if session.user_key != user_key:
                    raise UserStateNotFound("Study session not found")

                if session.is_submitted:
                    if not session.attempt_id:
                        raise UserStateAlreadySubmitted(
                            "Study session is already submitted"
                        )
                    committed_ref = client.collection(self._attempts_name).document(
                        session.attempt_id
                    )
                    committed_snapshot = await committed_ref.get(
                        transaction=transaction
                    )
                    if not committed_snapshot.exists:
                        raise UserStateAlreadySubmitted(
                            "Study session is already submitted"
                        )
                    committed = attempt_from_document(committed_snapshot.to_dict())
                    if (
                        committed.user_key != user_key
                        or committed.session_id != session_id
                    ):
                        raise UserStateAlreadySubmitted(
                            "Study session is already submitted"
                        )
                    return committed

                candidate_snapshot = await candidate_ref.get(transaction=transaction)
                if candidate_snapshot.exists:
                    existing = attempt_from_document(candidate_snapshot.to_dict())
                    if (
                        existing.user_key == user_key
                        and existing.session_id == session_id
                    ):
                        transaction.update(
                            session_ref,
                            {"is_submitted": True, "attempt_id": existing.id},
                        )
                        return existing
                    raise UserStateAlreadySubmitted("Study attempt already exists")

                progress_snapshot = await progress_ref.get(transaction=transaction)
                if progress_snapshot.exists:
                    progress = progress_from_document(progress_snapshot.to_dict())
                    if progress.user_key != user_key:
                        raise UserStateNotFound("Progress not found")
                else:
                    progress = empty_progress_projection(user_key)
                updated_progress = apply_attempt_to_projection(
                    progress,
                    candidate_attempt,
                )
                progress_document = progress_to_document(updated_progress)
                transaction.create(candidate_ref, candidate_document)
                transaction.update(
                    session_ref,
                    {
                        "is_submitted": True,
                        "attempt_id": candidate_attempt.id,
                    },
                )
                transaction.set(progress_ref, progress_document)
                return candidate_attempt

            return await commit_attempt(transaction)
        except UserStateError:
            raise
        except Exception as exc:
            raise UserStateUnavailable(
                "Study attempt storage is unavailable"
            ) from exc

    async def get_attempt(
        self,
        user_key: str,
        attempt_id: str,
    ) -> StudyAttempt:
        attempt_id = _validate_document_id(attempt_id, "Study attempt")
        try:
            client = await self._get_client()
            snapshot = await client.collection(self._attempts_name).document(
                attempt_id
            ).get()
            if not snapshot.exists:
                raise UserStateNotFound("Study attempt not found")
            attempt = attempt_from_document(snapshot.to_dict())
            if attempt.user_key != user_key:
                raise UserStateNotFound("Study attempt not found")
            return attempt
        except UserStateError:
            raise
        except Exception as exc:
            raise UserStateUnavailable(
                "Study attempt storage is unavailable"
            ) from exc

    async def get_progress(self, user_key: str) -> ProgressProjection:
        user_key = _validate_document_id(user_key, "Progress")
        try:
            client = await self._get_client()
            snapshot = await client.collection(self._progress_name).document(
                user_key
            ).get()
            if not snapshot.exists:
                return empty_progress_projection(user_key)
            progress = progress_from_document(snapshot.to_dict())
            if progress.user_key != user_key:
                raise UserStateNotFound("Progress not found")
            return progress
        except UserStateError:
            raise
        except Exception as exc:
            raise UserStateUnavailable("Progress storage is unavailable") from exc

    async def record_archive_practice(
        self,
        user_key: str,
        archive_question_id: int,
    ) -> ProgressProjection:
        user_key = _validate_document_id(user_key, "Progress")
        try:
            client = await self._get_client()
            progress_ref = client.collection(self._progress_name).document(user_key)
            claim_ref = (
                client.collection(self._claims_name).document(user_key)
                if user_key.startswith("anon-")
                else None
            )
            reset_ref = client.collection(self._resets_name).document(user_key)
            transactional = import_module(
                "google.cloud.firestore_v1"
            ).async_transactional

            @transactional
            async def record_in_transaction(transaction: Any) -> ProgressProjection:
                reset_snapshot = await reset_ref.get(transaction=transaction)
                claim_snapshot = (
                    await claim_ref.get(transaction=transaction)
                    if claim_ref is not None
                    else None
                )
                progress_snapshot = await progress_ref.get(transaction=transaction)
                if reset_snapshot.exists:
                    raise UserStateUnavailable("Progress reset is in progress")
                if claim_snapshot is not None and claim_snapshot.exists:
                    raise UserStateNotFound("User state is no longer available")
                if progress_snapshot.exists:
                    progress = progress_from_document(progress_snapshot.to_dict())
                    if progress.user_key != user_key:
                        raise UserStateNotFound("Progress not found")
                else:
                    progress = empty_progress_projection(user_key)
                updated = mark_archive_practiced(progress, archive_question_id)
                transaction.set(progress_ref, progress_to_document(updated))
                return updated

            return await record_in_transaction(client.transaction())
        except UserStateError:
            raise
        except Exception as exc:
            raise UserStateUnavailable("Progress storage is unavailable") from exc

    async def _delete_owner_documents(
        self,
        client: Any,
        collection: Any,
        user_key: str,
    ) -> int:
        deleted = 0
        while True:
            snapshots: list[Any] = []
            query = collection.where("user_key", "==", user_key).limit(
                FIRESTORE_BATCH_WRITE_LIMIT
            )
            async for snapshot in query.stream():
                snapshots.append(snapshot)
            if not snapshots:
                return deleted
            batch = client.batch()
            for snapshot in snapshots:
                batch.delete(snapshot.reference)
            await batch.commit()
            deleted += len(snapshots)

    async def reset_progress(self, user_key: str) -> UserStateResetSummary:
        user_key = _validate_document_id(user_key, "Progress")
        try:
            client = await self._get_client()
            sessions = client.collection(self._sessions_name)
            attempts = client.collection(self._attempts_name)
            progress_ref = client.collection(self._progress_name).document(user_key)
            reset_ref = client.collection(self._resets_name).document(user_key)
            target_claim_ref = client.collection(self._claim_targets_name).document(
                user_key
            )
            claim_ref = (
                client.collection(self._claims_name).document(user_key)
                if user_key.startswith("anon-")
                else None
            )
            transactional = import_module(
                "google.cloud.firestore_v1"
            ).async_transactional

            @transactional
            async def begin_reset(transaction: Any) -> None:
                reset_snapshot = await reset_ref.get(transaction=transaction)
                target_claim_snapshot = await target_claim_ref.get(
                    transaction=transaction
                )
                claim_snapshot = (
                    await claim_ref.get(transaction=transaction)
                    if claim_ref is not None
                    else None
                )
                if target_claim_snapshot.exists:
                    raise UserStateUnavailable("Progress claim is in progress")
                if claim_snapshot is not None and claim_snapshot.exists:
                    control = claim_snapshot.to_dict()
                    if (
                        control.get("user_key") != user_key
                        or str(control.get("status", ""))
                        not in {"claiming", "claimed"}
                    ):
                        raise UserStateUnavailable(
                            "Guest claim state is unavailable"
                        )
                    raise UserStateNotFound("User state is no longer available")
                if reset_snapshot.exists:
                    control = reset_snapshot.to_dict()
                    if (
                        control.get("user_key") != user_key
                        or control.get("status") != "resetting"
                    ):
                        raise UserStateUnavailable(
                            "Progress reset state is unavailable"
                        )
                    return
                now = datetime.now(UTC)
                transaction.create(
                    reset_ref,
                    {
                        "schema_version": 1,
                        "user_key": user_key,
                        "status": "resetting",
                        "started_at": now,
                        "updated_at": now,
                    },
                )

            await begin_reset(client.transaction())
            sessions_deleted = await self._delete_owner_documents(
                client,
                sessions,
                user_key,
            )
            attempts_deleted = await self._delete_owner_documents(
                client,
                attempts,
                user_key,
            )

            @transactional
            async def finalize_reset(transaction: Any) -> bool:
                reset_snapshot = await reset_ref.get(transaction=transaction)
                progress_snapshot = await progress_ref.get(transaction=transaction)
                if not reset_snapshot.exists:
                    return False
                control = reset_snapshot.to_dict()
                if (
                    control.get("user_key") != user_key
                    or control.get("status") != "resetting"
                ):
                    raise UserStateUnavailable(
                        "Progress reset state is unavailable"
                    )
                if progress_snapshot.exists:
                    transaction.delete(progress_ref)
                transaction.delete(reset_ref)
                return progress_snapshot.exists

            progress_deleted = await finalize_reset(client.transaction())
            return UserStateResetSummary(
                sessions_deleted=sessions_deleted,
                attempts_deleted=attempts_deleted,
                progress_deleted=progress_deleted,
            )
        except UserStateError:
            raise
        except Exception as exc:
            raise UserStateUnavailable("Progress reset is unavailable") from exc

    async def _commit_owner_updates(
        self,
        client: Any,
        snapshots: list[Any],
        guest_user_key: str,
        target_user_key: str,
    ) -> None:
        reset_ref = client.collection(self._resets_name).document(target_user_key)
        target_claim_ref = client.collection(self._claim_targets_name).document(
            target_user_key
        )
        transactional = import_module(
            "google.cloud.firestore_v1"
        ).async_transactional
        for offset in range(0, len(snapshots), FIRESTORE_BATCH_WRITE_LIMIT):
            batch_snapshots = snapshots[
                offset : offset + FIRESTORE_BATCH_WRITE_LIMIT
            ]

            @transactional
            async def commit_updates(transaction: Any) -> None:
                reset_snapshot = await reset_ref.get(transaction=transaction)
                target_claim_snapshot = await target_claim_ref.get(
                    transaction=transaction
                )
                if reset_snapshot.exists:
                    raise UserStateUnavailable("Progress reset is in progress")
                if not target_claim_snapshot.exists:
                    raise UserStateUnavailable("Progress claim is unavailable")
                target_control = target_claim_snapshot.to_dict()
                if (
                    target_control.get("guest_user_key") != guest_user_key
                    or target_control.get("target_user_key") != target_user_key
                    or target_control.get("status") != "claiming"
                ):
                    raise UserStateUnavailable("Progress claim is unavailable")
                for snapshot in batch_snapshots:
                    transaction.update(
                        snapshot.reference,
                        {"user_key": target_user_key},
                    )

            await commit_updates(client.transaction())

    async def _transfer_owner_documents(
        self,
        client: Any,
        collection: Any,
        guest_user_key: str,
        target_user_key: str,
    ) -> None:
        while True:
            snapshots = await self._query_by_owner(collection, guest_user_key)
            if not snapshots:
                return
            await self._commit_owner_updates(
                client,
                snapshots,
                guest_user_key,
                target_user_key,
            )

    async def claim_guest_state(
        self,
        guest_user_key: str,
        target_user_key: str,
    ) -> ProgressProjection:
        guest_user_key = _validate_document_id(guest_user_key, "Guest progress")
        target_user_key = _validate_document_id(target_user_key, "Progress")
        if not guest_user_key.startswith("anon-"):
            raise UserStateNotFound("Guest state is not available")
        if guest_user_key == target_user_key:
            return await self.get_progress(target_user_key)
        try:
            client = await self._get_client()
            sessions = client.collection(self._sessions_name)
            attempts = client.collection(self._attempts_name)
            progress_collection = client.collection(self._progress_name)
            guest_progress_ref = progress_collection.document(guest_user_key)
            target_progress_ref = progress_collection.document(target_user_key)
            claim_ref = client.collection(self._claims_name).document(
                guest_user_key
            )
            guest_reset_ref = client.collection(self._resets_name).document(
                guest_user_key
            )
            target_reset_ref = client.collection(self._resets_name).document(
                target_user_key
            )
            target_claim_ref = client.collection(
                self._claim_targets_name
            ).document(target_user_key)
            transactional = import_module(
                "google.cloud.firestore_v1"
            ).async_transactional

            @transactional
            async def begin_claim(transaction: Any) -> str:
                guest_reset_snapshot = await guest_reset_ref.get(
                    transaction=transaction
                )
                target_reset_snapshot = await target_reset_ref.get(
                    transaction=transaction
                )
                snapshot = await claim_ref.get(transaction=transaction)
                target_claim_snapshot = await target_claim_ref.get(
                    transaction=transaction
                )
                if guest_reset_snapshot.exists or target_reset_snapshot.exists:
                    raise UserStateUnavailable("Progress reset is in progress")
                if snapshot.exists:
                    control = snapshot.to_dict()
                    if (
                        control.get("user_key") != guest_user_key
                        or control.get("target_user_key") != target_user_key
                    ):
                        raise UserStateNotFound(
                            "Guest state is no longer available"
                        )
                    claim_status = str(control.get("status", ""))
                    if claim_status not in {"claiming", "claimed"}:
                        raise UserStateUnavailable(
                            "Guest claim state is unavailable"
                        )
                    if target_claim_snapshot.exists:
                        target_control = target_claim_snapshot.to_dict()
                        if (
                            target_control.get("guest_user_key")
                            != guest_user_key
                            or target_control.get("target_user_key")
                            != target_user_key
                            or target_control.get("status") != "claiming"
                        ):
                            raise UserStateUnavailable(
                                "Progress claim is unavailable"
                            )
                        if claim_status == "claimed":
                            transaction.delete(target_claim_ref)
                    elif claim_status == "claiming":
                        now = datetime.now(UTC)
                        transaction.create(
                            target_claim_ref,
                            {
                                "schema_version": 1,
                                "guest_user_key": guest_user_key,
                                "target_user_key": target_user_key,
                                "status": "claiming",
                                "started_at": now,
                                "updated_at": now,
                            },
                        )
                    return claim_status
                if target_claim_snapshot.exists:
                    raise UserStateUnavailable("Another progress claim is in progress")
                now = datetime.now(UTC)
                transaction.create(
                    claim_ref,
                    {
                        "schema_version": 1,
                        "user_key": guest_user_key,
                        "target_user_key": target_user_key,
                        "status": "claiming",
                        "projection_merged": False,
                        "guest_progress_existed": None,
                        "started_at": now,
                        "updated_at": now,
                        "claimed_at": None,
                    },
                )
                transaction.create(
                    target_claim_ref,
                    {
                        "schema_version": 1,
                        "guest_user_key": guest_user_key,
                        "target_user_key": target_user_key,
                        "status": "claiming",
                        "started_at": now,
                        "updated_at": now,
                    },
                )
                return "claiming"

            claim_status = await begin_claim(client.transaction())
            if claim_status == "claimed":
                return await self.get_progress(target_user_key)

            @transactional
            async def merge_progress(transaction: Any) -> ProgressProjection:
                guest_reset_snapshot = await guest_reset_ref.get(
                    transaction=transaction
                )
                target_reset_snapshot = await target_reset_ref.get(
                    transaction=transaction
                )
                target_claim_snapshot = await target_claim_ref.get(
                    transaction=transaction
                )
                claim_snapshot = await claim_ref.get(transaction=transaction)
                guest_snapshot = await guest_progress_ref.get(
                    transaction=transaction
                )
                target_snapshot = await target_progress_ref.get(
                    transaction=transaction
                )
                if guest_reset_snapshot.exists or target_reset_snapshot.exists:
                    raise UserStateUnavailable("Progress reset is in progress")
                if not target_claim_snapshot.exists:
                    raise UserStateUnavailable("Progress claim is unavailable")
                target_control = target_claim_snapshot.to_dict()
                if (
                    target_control.get("guest_user_key") != guest_user_key
                    or target_control.get("target_user_key") != target_user_key
                    or target_control.get("status") != "claiming"
                ):
                    raise UserStateUnavailable("Progress claim is unavailable")
                if not claim_snapshot.exists:
                    raise UserStateUnavailable("Guest claim state is unavailable")
                control = claim_snapshot.to_dict()
                if (
                    control.get("user_key") != guest_user_key
                    or control.get("target_user_key") != target_user_key
                ):
                    raise UserStateNotFound("Guest state is no longer available")

                if target_snapshot.exists:
                    target_progress = progress_from_document(
                        target_snapshot.to_dict()
                    )
                    if target_progress.user_key != target_user_key:
                        raise UserStateNotFound("Progress not found")
                else:
                    target_progress = empty_progress_projection(target_user_key)
                if control.get("status") == "claimed" or control.get(
                    "projection_merged"
                ) is True:
                    return target_progress

                if guest_snapshot.exists:
                    guest_progress = progress_from_document(
                        guest_snapshot.to_dict()
                    )
                    if guest_progress.user_key != guest_user_key:
                        raise UserStateNotFound("Guest progress not found")
                else:
                    guest_progress = empty_progress_projection(guest_user_key)
                merged = merge_progress_projections(
                    target_progress,
                    guest_progress,
                    target_user_key,
                )
                if guest_snapshot.exists:
                    transaction.set(
                        target_progress_ref,
                        progress_to_document(merged),
                    )
                transaction.update(
                    claim_ref,
                    {
                        "projection_merged": True,
                        "guest_progress_existed": guest_snapshot.exists,
                        "updated_at": datetime.now(UTC),
                    },
                )
                return merged

            await merge_progress(client.transaction())

            # The claim tombstone prevents new guest writes. Ownership changes
            # can therefore be safely resumed a batch at a time after failure.
            await self._transfer_owner_documents(
                client,
                sessions,
                guest_user_key,
                target_user_key,
            )
            await self._transfer_owner_documents(
                client,
                attempts,
                guest_user_key,
                target_user_key,
            )

            @transactional
            async def finalize_claim(transaction: Any) -> None:
                guest_reset_snapshot = await guest_reset_ref.get(
                    transaction=transaction
                )
                target_reset_snapshot = await target_reset_ref.get(
                    transaction=transaction
                )
                target_claim_snapshot = await target_claim_ref.get(
                    transaction=transaction
                )
                snapshot = await claim_ref.get(transaction=transaction)
                if guest_reset_snapshot.exists or target_reset_snapshot.exists:
                    raise UserStateUnavailable("Progress reset is in progress")
                if not target_claim_snapshot.exists:
                    raise UserStateUnavailable("Progress claim is unavailable")
                target_control = target_claim_snapshot.to_dict()
                if (
                    target_control.get("guest_user_key") != guest_user_key
                    or target_control.get("target_user_key") != target_user_key
                    or target_control.get("status") != "claiming"
                ):
                    raise UserStateUnavailable("Progress claim is unavailable")
                if not snapshot.exists:
                    raise UserStateUnavailable("Guest claim state is unavailable")
                control = snapshot.to_dict()
                if (
                    control.get("user_key") != guest_user_key
                    or control.get("target_user_key") != target_user_key
                ):
                    raise UserStateNotFound("Guest state is no longer available")
                if control.get("status") == "claimed":
                    transaction.delete(target_claim_ref)
                    return
                if control.get("projection_merged") is not True:
                    raise UserStateUnavailable("Guest claim state is unavailable")
                now = datetime.now(UTC)
                transaction.update(
                    claim_ref,
                    {
                        "status": "claimed",
                        "updated_at": now,
                        "claimed_at": now,
                    },
                )
                if control.get("guest_progress_existed") is True:
                    transaction.delete(guest_progress_ref)
                transaction.delete(target_claim_ref)

            await finalize_claim(client.transaction())
            return await self.get_progress(target_user_key)
        except UserStateError:
            raise
        except Exception as exc:
            raise UserStateUnavailable("Progress claim is unavailable") from exc

    async def healthcheck(self) -> None:
        try:
            client = await self._get_client()
            await client.collection(self._progress_name).limit(1).get()
        except UserStateError:
            raise
        except Exception as exc:
            raise UserStateUnavailable("Firestore user state is unavailable") from exc
