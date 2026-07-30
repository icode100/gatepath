# Gatepath 2027

Gatepath is a distraction-free GATE 2027 Computer Science preparation platform. It combines an official-syllabus roadmap, chapter-wise revision notes, topic-filtered practice, sectional tests, a provenance-aware previous-year question bank, progress tracking, and a full-length exam simulator.

The product uses a React/Next.js frontend and a FastAPI backend. SQLite works for local development; PostgreSQL is used by the Docker Compose stack.

## Official exam format

The full mock follows the current IIT Madras GATE 2027 pattern:

- 180 minutes
- 65 questions, not 56
- 10 General Aptitude questions and 55 subject questions
- 100 marks total: 15 GA, 13 Engineering Mathematics, and 72 other CS marks
- MCQ, MSQ, and NAT questions worth 1 or 2 marks
- MCQ penalties of 1/3 or 2/3 marks for incorrect answers
- no negative marks for MSQ or NAT, and no partial credit for MSQ

The question type mix is deliberately not hard-coded because IIT Madras has not published a fixed MCQ/MSQ/NAT count.

## Included features

- Interactive roadmap for every official CS syllabus section and topic
- Subject workspace with `Revise`, `Practice`, and `Sectional test` actions
- Topic-specific revision notes with key ideas, formulas, checkpoints, common traps, and at least three worked bank examples
- Topic-, subject-, type-, difficulty-, and year-filterable question APIs
- MCQ, MSQ, and NAT practice with explanations and official marking behavior
- 2,607-question local JSON bank: 2,220 distinct reproducible syllabus-bounded variants plus 387 safely verified PYQs
- 25 distinct full mocks: 65 questions, 100 marks, and 180 minutes each
- 100 course tests: 10 per technical course, 30 questions each, with MCQ, MSQ, and NAT coverage
- Topic mastery analytics, strong/needs-practice lists, roadmap progress, and attempt summaries
- Immutable test snapshots, deadline enforcement, and signed anonymous progress isolation
- Light and dark themes with responsive keyboard- and touch-friendly UI
- Local fallback content when the API is unavailable
- Conservative 845-record extraction audit for all 13 supplied 2017-2025 papers; uncertain OCR and visual questions remain quarantined instead of being guessed

## Start everything with Docker

Prerequisites: Docker Engine with Docker Compose.

```bash
cp .env.example .env
docker compose up --build -d
```

Before public deployment, set `ENVIRONMENT=production`, replace both
`POSTGRES_PASSWORD` and `ANONYMOUS_IDENTITY_SECRET` in `.env`, and serve the
app over HTTPS. Use a URL-safe database password; if it contains reserved URI
characters, set a percent-encoded `DATABASE_URL` instead. The backend requires
an identity secret of at least 32 characters and refuses the shipped
development value in production.

Open:

- Application: http://localhost:3000
- API documentation: http://localhost:8000/docs
- API health: http://localhost:8000/health

PostgreSQL data is retained in the `gatepath_postgres` named volume.

## Local development

Prerequisites: Python 3.11 or newer (3.12 recommended) and Node.js 22.13 or
newer.

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

The default local database is SQLite. Copy `backend/.env.example` to `backend/.env` to override settings.

### Frontend

```bash
npm ci
npm run dev
```

The frontend runs at http://localhost:3000 and proxies `/api/v1/*` to the
backend. Set `BACKEND_INTERNAL_URL` when the API is on another internal host.
The supported browser deployment is same-origin through this proxy (or
same-site subdomains); unrelated frontend/API domains are not supported by the
default `SameSite=Lax` anonymous cookie.

## Verification

```bash
cd backend
pytest
python scripts/validate_pyq_consolidation.py
python scripts/validate_question_bank.py

cd ..
npm run typecheck
npm run build
```

To validate the deployment definition without starting containers:

```bash
docker compose config
```

## Question-bank and PYQ pipeline

`backend/data/question_bank.json` is the authoritative local updater. Startup
validates and imports it idempotently, records a checksum audit, reactivates
questions when an older bank is deliberately restored, and retires omitted
import-managed rows without breaking historical attempts.

The supplied archive is represented by exactly 845 audit rows in
`backend/data/pyq_consolidated.json`. Of those, 387 verified rows are eligible
for quizzes and 458 remain `review_required`. The live bank never imports a
review-required row. Both 2017 papers and the 2020 paper remain fully accounted
for in the audit but have no live rows because their recovered text could not
be aligned to the official keys without OCR/header contamination, split
content, or incomplete options.

To regenerate the deterministic originals, merge the verified PYQs, and run
the strict bank validator:

```bash
cd backend
python scripts/generate_question_bank.py --validate
```

`backend/data/question_bank_manifest.json` records counts by course, topic,
type, mark value, and PYQ year. `backend/data/pyq_extraction_manifest.json`
records every source paper, safe/review counts, source URLs, and rejection
reasons. A legacy importer remains available for separately curated JSON:

```bash
python scripts/import_questions.py data/question_import_template.json --dry-run
python scripts/import_questions.py path/to/verified_questions.json
```

See [backend/README.md](backend/README.md) for the complete API contract and importer schema.

## Project layout

```text
app/                 React application and local study content
backend/app/         FastAPI routes, models, scoring, and seed logic
backend/migrations/  Alembic database migrations
backend/tests/       API and marking-rule tests
backend/data/        Live bank, 845-record PYQ audit, and validation manifests
backend/scripts/     Extraction, generation, validation, and import tools
public/              Frontend static assets
Dockerfile           Production frontend image
docker-compose.yml   Frontend, API, and PostgreSQL stack
```

## Authoritative sources

- [GATE 2027 question paper pattern](https://gate2027.iitm.ac.in/question_paper_pattern)
- [GATE 2027 CS syllabus](https://gate2027.iitm.ac.in/static/doc/GATE2027_Syllabus/CS_GATE2027_Syllabus.pdf)
- [GATE 2027 syllabus index](https://gate2027.iitm.ac.in/exam_papers_and_syllabus)
- [Official previous papers and answer keys](https://gate2027.iitm.ac.in/download)

Gatepath is an independent preparation tool and is not affiliated with IIT Madras or the GATE organizing committee.
