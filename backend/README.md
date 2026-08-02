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
paths are resolved from the backend directory. PostgreSQL always stores the
syllabus, notes, question bank, import audit, and deterministic test catalog.
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

User-state selection is independent of catalog storage:

```text
USER_STATE_BACKEND=postgres
FIRESTORE_DATABASE_ID=(default)
FIRESTORE_COLLECTION_PREFIX=gatepath
```

With `USER_STATE_BACKEND=firestore`, the backend reuses
`FIREBASE_SERVICE_ACCOUNT_JSON` (or Application Default Credentials) for
Firestore Admin access. The browser never connects to Firestore directly.
Deploy the repository's deny-all Firestore rules and index exemptions before
switching the backend. PostgreSQL remains required for every mode.

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

## Main API contract

All application endpoints use `/api/v1`.

- `GET /roadmap` — ordered, clickable subject/topic tree with progress for the current signed anonymous identity.
- `GET /subjects` and `GET /subjects/{id-or-slug}` — curriculum and topic details.
- `GET /topics/{id}` and `GET /topics/{id}/notes` — topic metadata and Markdown revision content.
- `GET /questions` — filters: `subject_id`, `subject_slug`, `topic_id`, `source_kind`, `year`, `question_type`, `difficulty`, `limit`, `offset`.
- `POST /practice-sessions` — creates an untimed filtered practice set.
- `GET /tests/catalog` — lists 125 stable forms: 25 full mocks and 100 course tests. Optional filters are `mode` and `subject_slug`.
- `POST /tests/{catalog_id}/sessions` — starts an immutable session snapshot for a catalog form.
- `POST /tests` — preserves ad-hoc sectional/full-test creation. Full tests use the fixed 65-question, 180-minute, 100-mark pattern (10 GA and 55 subject questions).
- `GET /sessions/{id}` — restores an active session and its timer metadata.
- `POST /attempts` — submits answers once, scores every question, then reveals solutions.
- `GET /attempts/{id}` — retrieves a submitted result.
- `GET /progress/dashboard` — aggregate and per-subject performance.
- `GET /progress/analytics` — per-topic accuracy, volume, coverage, recency-weighted accuracy, mastery and strong/needs-practice classifications.
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
and retirement counts. The migration chain is verified through a fresh
upgrade, full downgrade to base, and re-upgrade to head.
