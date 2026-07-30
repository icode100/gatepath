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
- Revision notes with key ideas, formulas, worked examples, checkpoints, and common traps
- Topic-, subject-, type-, difficulty-, and year-filterable question APIs
- MCQ, MSQ, and NAT practice with explanations and official marking behavior
- A 12-question live COA syllabus quiz covering all six official GATE 2027 areas
- 65-question, 180-minute full mock with question palette and mark-for-review
- Attempt scoring, subject analysis, roadmap progress, and activity summaries
- Light and dark themes with responsive keyboard- and touch-friendly UI
- Local fallback content when the API is unavailable
- 88 seeded questions, including 18 verified official GATE 2024 CS1 PYQs with paper and answer-key provenance
- JSON import workflow for expanding the official 2007-2026 archive

## Start everything with Docker

Prerequisites: Docker Engine with Docker Compose.

```bash
cp .env.example .env
docker compose up --build
```

Open:

- Application: http://localhost:3000
- API documentation: http://localhost:8000/docs
- API health: http://localhost:8000/health

PostgreSQL data is retained in the `gatepath_postgres` named volume. Replace the development password in `.env` before deploying.

## Local development

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

The frontend runs at http://localhost:3000 and proxies `/api/v1/*` to the backend. Set `BACKEND_INTERNAL_URL` when the API is on another host. `NEXT_PUBLIC_API_URL` can override the browser-visible API base.

## Verification

```bash
cd backend
pytest

cd ..
npm run typecheck
npm run build
```

To validate the deployment definition without starting containers:

```bash
docker compose config
```

## Previous-year question imports

The seed database includes a curated official 2024 set. To add more tagged questions:

```bash
cd backend
python scripts/import_questions.py data/question_import_template.json --dry-run
python scripts/import_questions.py path/to/questions.json
```

Every imported PYQ can retain its year, paper, question number, official paper URL, and official answer-key URL. Only use official papers and keys, then review topic tags and mathematical formatting before publishing.

See [backend/README.md](backend/README.md) for the complete API contract and importer schema.

## Project layout

```text
app/                 React application and local study content
backend/app/         FastAPI routes, models, scoring, and seed logic
backend/migrations/  Alembic database migrations
backend/tests/       API and marking-rule tests
backend/data/        Question import template
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
