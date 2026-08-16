# GATE 2027 Prep API

FastAPI backend for a distraction-free GATE CSE preparation application. It provides the syllabus roadmap, revision notes, a versioned local question bank, deterministic test forms, official-style scoring, and topic mastery analytics.

## Run locally

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs` for the interactive OpenAPI documentation. On startup the service:

1. creates the schema when `AUTO_CREATE_DB=true`;
2. idempotently seeds the syllabus and built-in fallback questions;
3. imports `data/question_bank.json` when it exists and `AUTO_IMPORT_QUESTION_BANK=true`;
4. deterministically materializes 25 full mocks and 10 course tests for each of the 10 technical courses.

The default bank location can be changed with `QUESTION_BANK_PATH`. Relative
paths are resolved from the backend directory. PostgreSQL is the default
catalog backend; a verified immutable Firestore publication can be selected
with `QUESTION_CATALOG_BACKEND=firestore` after learner state uses Firestore.
`USER_STATE_BACKEND=postgres` keeps mutable sessions, attempts, and progress in
the same database; production uses `USER_STATE_BACKEND=firestore` after the
documented migration. Firestore uses `FIRESTORE_DATABASE_ID=(default)` and the
fixed `gatepath` collection prefix so the deployed deny-all rules and index
exemptions always match the runtime target.

Progress is scoped to a signed, HttpOnly anonymous cookie or a verified
Firebase account session. The API ignores client-supplied identity values. The
supported browser topology is same-origin through the included Next.js proxy,
or same-site subdomains with credentials included. Unrelated cross-site
frontend/API domains are not supported by the default `SameSite=Lax` cookie.
Set a strong `ANONYMOUS_IDENTITY_SECRET` and enable HTTPS before public
deployment.

Run tests with:

```powershell
pytest
```

## Container

```powershell
docker build -t gate-prep-api .
docker run --rm -p 8000:8000 --env-file .env gate-prep-api
```

SQLite is the zero-configuration default. For PostgreSQL set, for example:

```text
DATABASE_URL=postgresql+asyncpg://gate:gate@postgres:5432/gate_prep
```

The PostgreSQL catalog works with either user-state backend. Firestore catalog
mode requires Firestore user state because its canonical question IDs are not
representable by the legacy relational attempt schema:

```text
USER_STATE_BACKEND=postgres
QUESTION_CATALOG_BACKEND=postgres
FIRESTORE_DATABASE_ID=(default)
FIRESTORE_COLLECTION_PREFIX=gatepath
FIRESTORE_CATALOG_CACHE_SECONDS=300
```

With `USER_STATE_BACKEND=firestore`, the backend reuses
`FIREBASE_SERVICE_ACCOUNT_JSON` (or Application Default Credentials) for
Firestore Admin access. The browser never connects to Firestore directly.
Deploy the repository's deny-all Firestore rules and index exemptions before
switching either backend. PostgreSQL remains the fallback while either flag is
`postgres`; it is no longer a runtime dependency after both flags are
`firestore` and the two migrations have been verified.

For managed deployments, set `AUTO_CREATE_DB=false` and run
`alembic upgrade head` before starting the service. The included Compose stack
does this automatically before launching Uvicorn. Set
`ENVIRONMENT=production`, provide a non-default
`ANONYMOUS_IDENTITY_SECRET`, set `IDENTITY_COOKIE_SECURE=true`, and serve the
frontend/API over HTTPS.

## Firestore learner-state cutover

Create a Firestore Standard database named `(default)` and choose a region near
the FastAPI deployment and PostgreSQL catalog database. Keep the runtime on
`USER_STATE_BACKEND=postgres` while preparing and verifying the copy. From the
repository root on a trusted workstation with both Neon and Firebase Admin
environment variables configured, run:

```powershell
python backend/scripts/migrate_user_state_to_firestore.py --dry-run
python backend/scripts/migrate_user_state_to_firestore.py --apply
python backend/scripts/migrate_user_state_to_firestore.py --verify-only
```

This is an explicit operational migration, never a startup hook, Vercel build
step, or cold-start action. Use a maintenance window, switch Production to
`USER_STATE_BACKEND=firestore`, and redeploy only after verification succeeds.
Legacy PostgreSQL user-state rows remain available. Roll back by restoring
`USER_STATE_BACKEND=postgres` and redeploying; reconcile any attempts written
to Firestore after cutover before treating PostgreSQL as current again.

## Firestore question-catalog cutover

The catalog migration is explicit and non-destructive. It publishes all 5,163
canonical records (2,290 generated originals plus 2,873 audited PYQs), retains
lossless aliases for the 405 historical SQL PYQ IDs, and builds a separate
2,467-question active runtime projection. Runtime data is packed into
checksum-bound immutable shards so a Vercel cold start does not read thousands
of individual Firestore documents.

Use a trusted workstation with a disposable, fully verified SQLite snapshot
and Firebase Admin credentials. The command is a dry run unless `--apply` is
present:

The optional export step rewrites only the dedicated
`firestore_legacy_catalog_snapshot.json`. The CLI refuses reviewed PYQ archive,
allowlist, and visibility-plan paths as snapshot outputs.

```powershell
python backend/scripts/migrate_catalog_to_firestore.py `
  --snapshot-from-sqlite backend/gate_prep.db `
  --source-snapshot backend/data/firestore_legacy_catalog_snapshot.json

python backend/scripts/migrate_catalog_to_firestore.py `
  --source-snapshot backend/data/firestore_legacy_catalog_snapshot.json `
  --manifest-out backend/data/firestore_catalog_release_manifest.json

python backend/scripts/migrate_catalog_to_firestore.py `
  --source-snapshot backend/data/firestore_legacy_catalog_snapshot.json `
  --apply `
  --confirm-release <exact-dry-run-release-id> `
  --expected-current-release none `
  --confirm-firestore-target "<project-id>|(default)|gatepath"

python backend/scripts/migrate_catalog_to_firestore.py --verify-only
```

Copy the exact `firestore_target.confirmation` value from the dry-run output.
Use `--expected-current-release none` only for the initial publication. Future
publishes must supply the exact current release ID; selecting an already
published older release also requires `--rollback`. The pointer is changed by a
transactional compare-and-swap only after immutable create-precondition writes
and exact verification succeed. Never delete the current pointer; publish or
rollback through this CLI. Remote modes reject `FIRESTORE_EMULATOR_HOST`
unless `--allow-firestore-emulator` is deliberately supplied for local testing.

Before the `--apply` command, set `DATABASE_URL` to the live target
Neon/PostgreSQL database that matches the frozen legacy snapshot. The apply
preflight deliberately rejects SQLite. The apply step verifies the tracked
`backend/data/firestore_catalog_release_manifest.json`; it does not regenerate
or overwrite that reviewed manifest.

Review the dry-run manifest and exact counts before applying. The publisher
writes into a new release namespace, verifies every document and shard, then
updates `gatepath_catalog_meta/current` last. Only after remote verification
passes and Production already uses `USER_STATE_BACKEND=firestore` should it set
`QUESTION_CATALOG_BACKEND=firestore` and redeploy. Never switch learner state
back to PostgreSQL while the Firestore catalog remains selected.

Retain Neon for rollback; the migration does not delete or mutate it. An
emergency catalog read fallback starts by restoring
`QUESTION_CATALOG_BACKEND=postgres`, but a full behavioral rollback requires a
maintenance window and deterministic canonical-to-legacy evidence
reconciliation for all 177 active audited questions. Immutable snapshots keep
sessions and attempts readable; PostgreSQL-backed practice rotation, roadmap,
and topic analytics are not exact until reconciliation finishes.

## Main API contract

All application endpoints use `/api/v1`.

- `GET /roadmap` — ordered, clickable subject/topic tree; completion counts unique active questions solved correctly at least once, so skipped/wrong/repeated responses cannot inflate it.
- `GET /subjects` and `GET /subjects/{id-or-slug}` — curriculum and topic details.
- `GET /topics/{id}` and `GET /topics/{id}/notes` — topic metadata and Markdown revision content.
- `GET /questions` — filters: `subject_id`, `subject_slug`, `topic_id`, `source`, `source_kind`, `year`, `question_type`, `difficulty`, and case-insensitive `search`; paginated with `limit` (default 50, maximum 100) and `offset`.
- `POST /practice-sessions` — creates an untimed filtered practice set.
- `GET /tests/catalog` — lists 125 stable forms: 25 full mocks and 100 course tests. Optional filters are `mode` and `subject_slug`.
- `POST /tests/{catalog_id}/sessions` — starts an immutable session snapshot for a catalog form.
- `POST /tests` — preserves ad-hoc sectional/full-test creation. Full tests use the fixed 65-question, 180-minute, 100-mark pattern (10 GA and 55 subject questions).
- `GET /sessions/{id}` — restores an active session and its timer metadata.
- `POST /attempts` — submits answers once, scores every question, then reveals solutions.
- `GET /attempts/{id}` — retrieves a submitted result.
- `GET /progress/dashboard` — aggregate and per-subject performance.
- `GET /progress/analytics` — per-topic accuracy, volume, coverage, recency-weighted accuracy, mastery and strong/needs-practice classifications.
- `POST /progress/reset` — CSRF-protected, explicit-confirmation reset of the current identity's sessions, attempts, and progress projection; static curriculum and question-bank data are never touched.
- `GET /question-bank/status` — current bank size and latest import audit record.
- `GET /health` — service and database readiness (this endpoint is at the service root, outside `/api/v1`).

Public question responses intentionally omit `correct_answer` and `explanation`. They are returned only after submission. Answers use an option ID for MCQ (`"B"`), an option-ID array for MSQ (`["A", "C"]`), and a number or numeric string for NAT (`3.14`).

Scoring follows GATE rules: incorrect MCQs lose one third of the question's marks; MSQ and NAT questions have no negative marking; unanswered questions score zero.

## Versioned local question bank

The updater accepts a UTF-8 JSON document at `backend/data/question_bank.json`:

```json
{
  "schema_version": "1.0",
  "bank_version": "gate-cs-2027-v1",
  "generated_at": "2026-07-30T00:00:00Z",
  "questions": [
    {
      "external_id": "gate-2025-cs1-q12",
      "question": "Question text",
      "options": [
        {"id": "A", "text": "First option"},
        {"id": "B", "text": "Second option"}
      ],
      "course": "COA",
      "topic": "Instruction Pipelining",
      "correct_answer": "A",
      "question_type": "mcq",
      "difficulty": "medium",
      "marks": 1,
      "explanation": "Solution or explanation",
      "numerical_tolerance": 0.01,
      "source_kind": "previous_year",
      "source_year": 2025,
      "source_paper": "GATE 2025 CS1",
      "source_question_number": 12,
      "source_page": 4,
      "source_url": "https://example.invalid/paper.pdf",
      "answer_key_url": "https://example.invalid/key.pdf",
      "extraction_method": "pdf-text",
      "extraction_confidence": 0.99,
      "tags": ["gate-2025", "official-pyq"]
    }
  ]
}
```

The five user-requested fields are `question`, `options`, `course`, `topic`, and `correct_answer`. The additional fields make question type, scoring and provenance unambiguous. `text` is accepted as an alias for `question`; string option arrays are normalized to `A`, `B`, and so on. If `question_type` is omitted, the updater infers NAT from an empty option list and MSQ from an answer array.

The updater may also carry a top-level `revision_notes` array keyed by the same
`course`/`topic` (or slug) scope. Each entry versions its `title`, `summary`,
three-or-more `key_points`, three-or-more `common_traps`, and
`reasoning_pattern` alongside the bank. Import renders these fields into the
topic note. For the shipped bank, it deterministically attaches at least three
worked examples from that topic's active original questions; unknown or
duplicate topic scopes fail before any database mutation.

`external_id` is the upsert key. If it is absent, a stable provenance- or
content-derived ID is generated. Re-importing the currently applied bytes is a
no-op. Reapplying a previously seen older artifact performs a full
reconciliation and then becomes idempotent again. A changed document updates
matching questions without duplication and retires omitted importer-managed
rows instead of deleting them, preserving completed attempts. Each unique
version/checksum audit row records inserted, updated, unchanged, and retired
counts. Unknown courses, conflicting slugs, duplicate provenance, or invalid
topics fail before any mutation.

The shipped release bank has 2,607 rows: 2,220 deterministic, semantically
distinct variants and 387 safely verified PYQs from 2018, 2019, and 2021-2025.
Every technical course has at least 227 questions, every canonical syllabus topic has
MCQ/MSQ/NAT coverage, and both
one- and two-mark questions are present.

## Audited extraction artifacts and reproducible bank validation

The supplied 2017-2025 archive is consolidated into exactly 845 audit records.
Only rows with `status="verified"` and `safe_for_quiz=true` are merged into the
live bank; all 458 uncertain rows remain available for manual review with
explicit flags and provenance.

```powershell
python scripts/validate_pyq_consolidation.py
python scripts/generate_question_bank.py --validate
python scripts/validate_question_bank.py
```

Those three commands are reproducible from the checked-in repository. The raw
extractor is also included, but a clean clone cannot recreate the reviewed OCR
transcriptions without the user-supplied archive and ignored review workspace.
It expects `CS.zip` to be expanded so its papers appear below
`tmp/pyq/source/CS/`, plus any replacement PDFs and reviewed OCR artifacts
referenced by `data/pyq_extraction_manifest.json`.

```powershell
# Non-writing diagnostic after staging the supplied files under tmp/pyq/
python scripts/extract_pyqs.py --cache-only --only CS2-2021
```

Embedded PDF text uses the pinned `pypdf` development dependency. OCR is
optional: the extractor uses locally staged `rapidocr_onnxruntime` packages
and rendered page images only when they exist. The committed 845-row audit and
manifests are the reviewed release artifacts; regenerating the live bank from
that audit does not require the ignored OCR workspace.

> **Release-artifact warning:** running the extractor without `--cache-only`
> rewrites `pyq_consolidated.json` and the extraction manifest. In particular,
> a filtered `--only` run would replace the complete 845-row audit with that
> subset. Keep diagnostics in cache-only mode unless you deliberately intend
> to rebuild and re-review the complete extraction release.

The generated artifacts are:

- `data/pyq_consolidated.json` — all 845 source slots and review state.
- `data/pyq_extraction_manifest.json` — paper coverage and rejection reasons.
- `data/question_bank.json` — the local database updater.
- `data/question_bank_manifest.json` — course/topic/type/marks/year counts.

The 2017 and 2020 rows remain quarantined because the recovered pages do not
provide clean question-to-key alignment without OCR metadata, watermarks,
headers, split content, or incomplete options. The pipeline intentionally
prefers a review flag over a guessed quiz answer.

The legacy command-line importer remains available for manually curated files:

```powershell
python scripts/import_questions.py data/question_import_template.json --dry-run
python scripts/import_questions.py path\to\verified_questions.json
```

### Paper-scoped legacy PYQ archive

Papers before the modern 65-question format contain hierarchical labels such
as `2.25`, descriptive subparts such as `24-b`, and questions that are no
longer in the GATE 2027 syllabus. They are ingested through the separate,
audited archive instead of being forced into the auto-scored question schema.
Every declared paper must contain exactly its expected number of contiguous
source items. Missing transcriptions remain explicit archive rows; they are
never silently omitted.

Build the review-only canonical skeleton before using the importer. The
builder reads the 39-paper source manifest, adopts only explicitly mapped
records from the existing consolidation, and optionally attaches secondary
locators without treating them as authoritative. Its default artifact and
audit report live under ignored `tmp/pyq/build`; it does not connect to a
database and every emitted row has `practice_eligible=false`.

```powershell
python scripts/build_canonical_pyq_archive.py

# Optional only after the incremental sanitized index is complete and stable.
python scripts/build_canonical_pyq_archive.py `
  --examside-index ..\tmp\pyq\reference\examside\examside_reference_index.jsonl
```

Modern paper sections retain collision-free labels (`GA-1` through `GA-10`
and `CS-1` through `CS-55`) while their global ordinals remain 1 through 65.
Explicit `source_aliases` in each paper record let the importer adopt older
labels such as `CS1-2024` without fuzzy cross-session matching. Per-item
`legacy_source_ordinals` encode audited numbering changes such as the
technical-first 2017 corpus; duplicate legacy targets are rejected.
The one code-held production compatibility alias is deliberately exact:
`GATE 2024 CS1 (Session 5)` maps only to `gate-cs-2024-set-1`.

The archive importer is read-only by default. A preview never runs Alembic and
fails safely if the database revision is stale. Apply the migration separately
before previewing, or use the importer's explicit `--apply --upgrade-schema`
path. It rejects a reused artifact version with a different checksum, scopes
every update to the papers declared by the artifact, and requires every live
apply to pin the reviewed active-original count. The clearly named
`--unsafe-allow-unpinned-originals` escape hatch is for disposable databases,
not production. Only `mcq`, `msq`, and `nat` rows with verified transcription,
answer, syllabus classification, solution, and no review flags can be
materialized for quizzes.

Before any database preview, run the stricter release gate against the final
immutable artifact. Unlike the importer schema, this validator does not accept
placeholder archive rows as a finished release: all 39 papers and 2,873
expanded records derived from the 2,712 canonical parent slots must be present,
every stem must have original-PDF page/hash evidence,
every syllabus classification must be final, and every objective answer must
be verified. Historical descriptive items may remain archive-only rather than
being misrepresented as MCQ/MSQ/NAT. The command is read-only and exits nonzero
while any release blocker remains.

```powershell
python scripts/validate_pyq_release_readiness.py data/pyq_archive.json `
  --report ..\tmp\pyq\build\release-readiness.json
```

The deployable package is published deterministically from the frozen staging
checkpoint. Its proof keeps all 20 unpublished extraction inputs as explicit
checksum-only lineage IDs; it never pretends that ignored `tmp` files exist in
a clean checkout and does not add the roughly 52 MB extraction worktree to the
deployment. The clean-checkout validator reads only the six tracked package
JSON files and the promoted same-origin PNGs:

```powershell
# Regenerate tracked files only from the exact frozen staging checkpoint.
python scripts/publish_pyq_release.py
python scripts/publish_pyq_release.py --check

# Works without tmp/pyq or any upstream extraction/policy JSON files.
python scripts/validate_published_pyq_package.py
```

Directly rebuilding promotion from the published archive report is
intentionally unsupported because its upstream lineage is checksum-only. The
promotion builder fails with an explicit message instead of following a fake
or missing file path; use the package validator above for tracked releases.

```powershell
# Explicit schema step. The preview command below will never do this itself.
python -m alembic -c alembic.ini upgrade head

# Validate source-slot completeness and preview eligible quiz rows.
python scripts/import_pyq_archive.py data/pyq_archive.json --materialize

# Production apply over DATABASE_URL_UNPOOLED after reviewing the dry run.
python scripts/import_pyq_archive.py data/pyq_archive.json `
  --apply --materialize --expected-active-originals 2290

# Equivalent explicit one-command schema upgrade + apply. This is rejected
# unless --apply is present.
python scripts/import_pyq_archive.py data/pyq_archive.json `
  --apply --upgrade-schema --materialize --expected-active-originals 2290
```

Materialization is non-retiring by default. The reviewed production-visibility
transition is a separate opt-in path bound to the exact published practice
artifact, source archive, promotion allowlist/report, collision evidence, and a
portable fingerprint ledger. Preview and apply both require the literal
`2290 / 405 / 228 / 177` guards; any mismatch aborts before importer ORM state
is changed:

```powershell
# Read-only preview.
python scripts/import_pyq_archive.py `
  data/gate_cs_pyq_practice_1996_2025.json --materialize --allow-retire `
  --expected-active-originals 2290 --expected-retirements 228 `
  --expected-active-pyqs-before 405 --expected-active-pyqs-after 177

# Apply only after reviewing the exact preview.
python scripts/import_pyq_archive.py `
  data/gate_cs_pyq_practice_1996_2025.json --apply --materialize --allow-retire `
  --expected-active-originals 2290 --expected-retirements 228 `
  --expected-active-pyqs-before 405 --expected-active-pyqs-after 177
```

The preview separates materialized insertions, legacy-row adoptions, updates,
and retirements. `pyq_archive_imports` continues to identify immutable artifact
bytes, while `pyq_archive_executions` records every live archive-only or
materialization execution, including repeated runs of the same artifact. A
guarded cleanup records the visibility-plan SHA and exact counts. It deactivates
rows only (`is_active=false`), never deletes questions or archive records, and
rebuilds and validates all 125 deterministic test forms inside the same
transaction so no form can reference an inactive question.

The current baseline contains 13 2024 Set 1 source collisions between the
early curated seed and the versioned question bank. Default materialization
does not delete or deactivate either row. It may adopt the exact bank
transcription only when both portable row fingerprints, the official paper and
answer-key checksums, the explicit paper aliases, and the reviewed
year/ordinal/type/answer/marks/URL proof all match
`data/pyq_legacy_collision_adoptions.json`. Any missing, additional, or changed
candidate fails before mutation. The non-selected seed row remains active and
recoverable unless the separately authorized visibility transition is applied.

`data/pyq_legacy_collision_cleanup_plan.json` is the checksum-pinned visibility
ledger. Its 177 keep records carry both the staging/source content hash and the
different promoted content hash; its 228 retirement fingerprints cover the 215
archive-only legacy rows plus the 13 reviewed paraphrase duplicates. The file
authorizes nothing by itself: execution still requires `--allow-retire` and all
literal guards above. Reusing that guarded command at 177 fails closed, while a
normal non-retiring materialization rerun is zero-change.

Recovery is also explicit, fingerprint-bound, audited, non-deleting, and
rebuilds the test catalog in the same transaction:

```powershell
# Read-only recovery preview; add --apply only after review.
python scripts/import_pyq_archive.py `
  data/gate_cs_pyq_practice_1996_2025.json --restore-retired `
  --expected-active-originals 2290 --expected-reactivations 228 `
  --expected-active-pyqs-before 177 --expected-active-pyqs-after 405
```

`scripts/build_pyq_visibility_plan.py` can reproduce the portable ledger only
from a disposable SQLite database at the exact `2695 questions / 2290 active
originals / 405 active PYQs / 2873 archive records` baseline. It refuses every
non-SQLite database URL.

The relational archive stores text and provenance only. Diagram crops are
versioned static assets referenced by checksum; database blobs are not used.
The no-argument command is deliberately bound to the tracked practice archive,
allowlist, promotion report, publication proof, asset manifest, and public
PNGs. It is safe in a clean checkout and cannot silently fall back to ignored
`tmp` inputs:

```powershell
python scripts/materialize_pyq_question_assets.py
python scripts/materialize_pyq_question_assets.py --check
```

The command refuses review/archive-only crops, remote paths, unexpected public
PNGs, stale promotion allowlists, and any source or copied checksum mismatch.
Regenerating from the ignored extraction checkpoint is a separate, explicit
developer action; it may rewrite the manifest's provenance and must be followed
by the tracked publisher/materializer checks before commit:

```powershell
python scripts/materialize_pyq_question_assets.py --staging
```

Equivalent custom staging inputs require all three explicit paths (`--release`,
`--allowlist`, and `--promotion-report`) under `tmp`; published custom paths
also require their checksum-bound `--publication-proof`.

## Test catalog rules

- Full forms: 25 deterministic forms, each containing 5 one-mark and 5 two-mark GA questions, 5 one-mark and 4 two-mark Engineering Mathematics questions, and 20 one-mark and 26 two-mark core CS questions. Every form is exactly 65 questions, 100 marks and 180 minutes, split as 15 GA + 13 EM + 72 core CS marks.
- Course forms: 10 deterministic forms for each of EM, DL, COA, PDS, ALG, TOC, CD, OS, DBMS and CN. Every available form has exactly 30 questions, includes MCQ/MSQ/NAT, and round-robins across syllabus topics.
- A form remains visible with `is_available=false` and an explicit reason if the local bank lacks the required count/type/mark mix. Rebuilding with the same bank yields the same question IDs.

## Analytics model

Topic analytics use four signals: answered-question accuracy (45%), 30-day
half-life recency-weighted accuracy (20%), practice volume capped at 10
answered questions (20%), and unique-question bank coverage (15%). Only the
latest answered response for each active question is mastery evidence: each
question contributes at most one evidence row, and a newer answered response
supersedes its earlier answer. Timeouts and unanswered rows do not affect
mastery. Scores are returned on a 0–100 scale. Topics are classified as
`strong`, `developing`, `needs_practice`, or `unattempted`; the API also
returns pre-sorted strong and needs-practice lists.

## Migrations

`0002_question_bank_catalog` adds stable question IDs, bank versions, import
audit records, persistent test forms, and the session-to-catalog reference.
`0003_release_hardening` adds active-bank membership, extraction metadata,
immutable session question snapshots, immutable answer/explanation snapshots,
and retirement counts. `0004_pyq_archive` adds canonical paper/item provenance;
`0005_pyq_archive_execution_audit` adds the immutable per-execution apply audit.
`0006_question_assets` adds same-origin, checksum-bound asset projections to
materialized questions while the archival table retains full provenance.
`0007_pyq_visibility_audit` records visibility-plan hashes and exact
reactivation counts for guarded cleanup and recovery executions.
The migration chain is verified through a fresh upgrade, full downgrade to
base, and re-upgrade to head.
