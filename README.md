# GatePath 2027

GatePath is a distraction-free GATE 2027 Computer Science preparation platform. It combines an official-syllabus roadmap, chapter-wise revision notes, topic-filtered practice, sectional tests, a provenance-aware previous-year question bank, progress tracking, and a full-length exam simulator.

The product uses a React/Next.js frontend and a FastAPI backend. SQLite works
for local development; PostgreSQL is used by Docker Compose and Neon provides
PostgreSQL on Vercel. PostgreSQL always owns the syllabus, question bank,
revision notes, and deterministic test catalog. Mutable learner state can use
PostgreSQL locally or Firestore in production. Firebase Authentication adds
optional account sign-in, with signed guest access retained when Firebase is
disabled. If an existing account session cannot be verified, owned writes fail
safely instead of being silently reassigned to a guest.

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

- Interactive roadmap for all 11 official CS/GA courses and 64 syllabus chapters
- Subject workspace with `Revise`, `Practice`, and `Sectional test` actions
- Dedicated Learn library with original guided lessons, prerequisites, objectives, formulas or methods, worked examples, and answer-reveal checkpoints
- Topic-specific revision notes with key ideas, common traps, authoritative IITM/NPTEL references, and at least three worked bank examples
- Topic-, subject-, type-, difficulty-, and year-filterable question APIs
- MCQ, MSQ, and NAT practice with explanations and official marking behavior
- 2,607-question local JSON bank: 2,220 distinct reproducible syllabus-bounded variants plus 387 safely verified PYQs
- 25 distinct full mocks: 65 questions, 100 marks, and 180 minutes each
- 100 course tests: 10 per technical course, 30 questions each, with MCQ, MSQ, and NAT coverage
- Per-user topic mastery analytics, strong/needs-practice lists, correct-only roadmap completion, attempt summaries, and an explicitly confirmed progress reset, with Firestore storage in production
- Immutable test snapshots, deadline enforcement, Firebase account ownership, and signed guest fallback
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

Firebase Authentication is disabled by default in the local template, so
Docker starts in signed guest mode without Firebase credentials. To exercise
account sign-in locally, follow [the Firebase guide](docs/firebase-vercel.md),
authorize `localhost`, and provide the Web SDK and Admin settings through an
ignored local environment file. Never add a service-account JSON file to an
image or commit.

Compose also defaults `USER_STATE_BACKEND=postgres`, keeping mutable learner
state in the local PostgreSQL container. Set it to `firestore` only when a
Firestore database and Firebase Admin credentials are available. This switch
does not move or delete existing PostgreSQL rows automatically.

Open:

- Application: http://localhost:3000
- API documentation: http://localhost:8000/docs
- API health: http://localhost:8000/health

PostgreSQL data is retained in the `gatepath_postgres` named volume.
Compose runs the explicit, idempotent database bootstrap before starting
Uvicorn, so `docker compose up` still prepares the schema, syllabus, question
bank, and test catalog in one command.

## Deploy to Vercel

The checked-in [`vercel.json`](vercel.json) deploys the repository as one
[Vercel Services](https://vercel.com/kb/guide/vercel-services) project:

- `frontend` builds the Next.js application from the repository root.
- `backend` builds `backend/app/main.py` with Vercel's native FastAPI runtime.
- `/api/v1/*`, `/health`, and the FastAPI documentation routes go directly to
  FastAPI; every other path goes to Next.js on the same deployment domain.

Vercel does not run `docker-compose.yml` or the PostgreSQL container. The
Docker files remain the local and portable self-hosted deployment path; Vercel
uses native framework services and an external managed database.

Neon remains required for static catalog data and explicit release bootstrap.
Firebase provides account sign-in and optional browser telemetry; Firestore is
the production source of truth for sessions, attempts, progress, and
topic-mastery analytics when `USER_STATE_BACKEND=firestore`. See the complete
[Firebase and Vercel setup guide](docs/firebase-vercel.md) before switching
learner state.

### 1. Import the GitHub repository

1. In Vercel, select **Add New → Project** and import
   `icode100/gatepath`.
2. Keep the project root at the repository root. Do not select `backend/`.
3. Open **Settings → Build and Deployment** and set **Framework Preset** to
   **Services**. This is required: Vercel only uses the `services` block when
   the project preset is Services.
4. Leave custom install, build, output, and development commands empty.
   `vercel.json` pins Next.js and FastAPI for their respective roots.

Services are currently Beta and available on all Vercel plans. If **Services**
does not appear in the framework list for the account, do not deploy the
repository as a plain Next.js project; use two Vercel projects as a temporary
fallback or request Services access.

### 2. Create and connect PostgreSQL catalog storage

1. In the project, open **Marketplace → Storage**, add
   [Neon](https://vercel.com/marketplace/neon), and create or connect a
   PostgreSQL database.
2. Enable Neon's preview-branch integration so every Vercel Preview deployment
   receives an isolated database branch.
3. In **Settings → Environment Variables**, confirm that Neon provides
   `DATABASE_URL`. Also retain its direct/non-pooled connection as
   `DATABASE_URL_UNPOOLED` for migrations and bootstrap work. If the
   integration uses differently named variables, add these two aliases.

The API accepts ordinary `postgresql://` and `postgres://` URLs and selects the
async PostgreSQL driver itself. PostgreSQL remains required after Firestore is
enabled because it owns all static curriculum and question-bank data. Never
prefix a browser-visible variable with a database secret.

### 3. Configure Firebase Authentication, Firestore, and optional Analytics

1. In the [Firebase Console](https://console.firebase.google.com/), register a
   Web app in the Firebase project.
2. Under **Authentication → Sign-in method**, enable **Email/Password** and
   **Google**.
3. Under **Authentication → Settings → Authorized domains**, add
   `gatepath.vercel.app` and the final custom domain. Add `localhost` only when
   local sign-in is needed.
4. Under **Project settings → Service accounts → Firebase Admin SDK**, generate
   a private key. Store its complete JSON object only as the sensitive Vercel
   variable `FIREBASE_SERVICE_ACCOUNT_JSON`; never commit it or expose it in a
   `NEXT_PUBLIC_` variable.
5. Under **Build → Firestore Database**, create the Standard edition database
   named `(default)`. Choose a region near both the Vercel backend functions and
   the Neon region; this choice is difficult to change after creation.
6. Deploy the deny-all browser rules and index configuration checked into this
   repository. FastAPI reuses the same Firebase Admin service-account JSON and
   bypasses these browser rules.
7. Copy the public Web SDK configuration into the corresponding
   `NEXT_PUBLIC_FIREBASE_*` Vercel variables listed below. Enable Analytics in
   **Project settings → Integrations** only if product telemetry is wanted.

Projects created after April 28, 2025 do not authorize `localhost` by default.
Generated Vercel preview hostnames also need deliberate authorization for
OAuth sign-in; guest access remains available on previews that are not
authorized. The detailed guide covers service-account handling, redirect-flow
constraints, Analytics privacy, and end-to-end smoke checks.

### 4. Configure Vercel environment variables

Add the following under **Settings → Environment Variables**. Apply the core
runtime settings to Production and Preview, and scope database URLs to their
corresponding Neon production or preview branch. Apply Firebase credentials
only to environments where account sign-in should work; set
`FIREBASE_AUTH_ENABLED=false` and omit the Admin secret on guest-only previews.

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | Neon pooled runtime URL |
| `DATABASE_URL_UNPOOLED` | Neon direct URL used by the bootstrap command |
| `USER_STATE_BACKEND` | `firestore` in Production; `postgres` is the safe default and rollback value |
| `USER_STATE_MAINTENANCE` | `false`; set `true` only for the brief learner-state migration window |
| `FIRESTORE_DATABASE_ID` | `(default)` |
| `FIRESTORE_COLLECTION_PREFIX` | `gatepath` |
| `ENVIRONMENT` | `production` |
| `ANONYMOUS_IDENTITY_SECRET` | A new random secret of at least 32 characters |
| `IDENTITY_COOKIE_SECURE` | `true` |
| `AUTO_BOOTSTRAP_ON_STARTUP` | `false` |
| `AUTO_CREATE_DB` | `false` |
| `SEED_DATA` | `false` |
| `AUTO_IMPORT_QUESTION_BANK` | `false` |
| `QUESTION_BANK_PATH` | `data/question_bank.json` |
| `SQL_ECHO` | `false` |
| `NEXT_PUBLIC_API_URL` | `/api/v1` |
| `NEXT_PUBLIC_FIREBASE_API_KEY` | Firebase Web SDK `apiKey` |
| `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN` | Firebase Web SDK `authDomain` |
| `NEXT_PUBLIC_FIREBASE_PROJECT_ID` | Firebase Web SDK `projectId` |
| `NEXT_PUBLIC_FIREBASE_APP_ID` | Firebase Web SDK `appId` |
| `NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID` | Optional Web SDK `measurementId` for Analytics |
| `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID` | Optional Web SDK `messagingSenderId` |
| `FIREBASE_AUTH_ENABLED` | `true` |
| `FIREBASE_PROJECT_ID` | Same Firebase project ID used by the web app |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Complete one-line service-account JSON; Sensitive and server-only |
| `FIREBASE_SESSION_COOKIE_NAME` | `gatepath_session` |
| `FIREBASE_CSRF_COOKIE_NAME` | `gatepath_csrf` |
| `FIREBASE_SESSION_MAX_AGE_SECONDS` | `432000` |
| `FIREBASE_RECENT_AUTH_SECONDS` | `300` |
| `FIREBASE_CHECK_REVOKED` | `false` (set `true` only if per-request revocation lookups are acceptable) |

Generate the identity secret locally, then paste only its output into Vercel:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

For Production, optionally set `NEXT_PUBLIC_SITE_URL` and `CORS_ORIGINS` to
the final `https://...` domain. Leave `NEXT_PUBLIC_SITE_URL` unset for Preview
so metadata follows each generated preview hostname. CORS is not required for
the application's normal same-origin browser requests. Do not set
`BACKEND_INTERNAL_URL` on Vercel; it is only used by the local Next.js/Docker
proxy. Vercel supplies `VERCEL=1` automatically.

The public Web SDK values identify the Firebase app and are intentionally
browser-visible. The service-account JSON is an Admin private key and must stay
server-only. Preserve its `private_key` `\n` escapes when storing the complete
object as one-line JSON. Vercel environment changes apply only to new
deployments, so redeploy after adding or rotating any Firebase value.

### 5. Bootstrap the target database once

Database migrations and the 2,607-question import must not run during a
serverless cold start or every Vercel build. From a trusted local checkout,
run the explicit bootstrap against the target Neon database:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
$env:DATABASE_URL = "<Neon pooled PostgreSQL URL>"
$env:DATABASE_URL_UNPOOLED = "<Neon direct PostgreSQL URL>"
.venv\Scripts\python scripts/bootstrap_database.py
Remove-Item Env:DATABASE_URL
Remove-Item Env:DATABASE_URL_UNPOOLED
```

The command upgrades Alembic to `head`, seeds the official syllabus, imports
the bundled question bank, and rebuilds all stable test forms. It is
idempotent. With the shipped release data, its success line reports 2,695
active questions (the 2,607-row bundled bank plus local seed/example rows) and
125 test forms. Run it before the first production promotion and again when a
release adds migrations or changes the bundled bank. Do not put this command
in Vercel's Build Command.

### 6. Migrate learner state and switch production

Do not change `USER_STATE_BACKEND` until the Firestore configuration has been
deployed and existing PostgreSQL learner state has been copied. From the
repository root on a trusted workstation, provide the Neon connection and the
same server-only Firebase Admin environment used by Vercel, then run:

```powershell
python backend/scripts/migrate_user_state_to_firestore.py --dry-run
python backend/scripts/migrate_user_state_to_firestore.py --apply
python backend/scripts/migrate_user_state_to_firestore.py --verify-only
```

Never run this migration during a Vercel build or function cold start. Use a
brief maintenance window so new attempts cannot arrive between copy and
verification. After verification succeeds, set the Production Vercel value to
`USER_STATE_BACKEND=firestore` and redeploy. The migration does not drop or
rewrite legacy Neon rows.

The production deployment intentionally exposes no HTTP migration endpoint.
If Vercel's Sensitive variables cannot be read back, create a short-lived
Firebase Admin credential for a trusted workstation, run the checked-in CLI,
and revoke that credential immediately after verification. Keep
`USER_STATE_MAINTENANCE=true` for the complete copy-and-verify window, then set
it back to `false` when switching to Firestore.

For a rollback, set `USER_STATE_BACKEND=postgres` and redeploy. This restores
the pre-cutover PostgreSQL view while leaving Firestore untouched. Attempts
created after the Firestore cutover require reconciliation before PostgreSQL
can again be considered current, so keep the initial validation window short.
The detailed guide includes the rules/index deployment, free-tier capacity and
retention notes, and smoke checks. Neon storage no longer grows with users in
Firestore mode, although Neon remains required for catalog reads and Firestore
retains its own usage quotas.

### 7. Deploy and verify

Push to the connected branch or select **Deploy** in Vercel, then verify:

```text
https://<deployment-domain>/health
https://<deployment-domain>/api/v1/question-bank/status
https://<deployment-domain>/api/v1/auth/csrf
https://<deployment-domain>/api/v1/auth/me
https://<deployment-domain>/docs
https://<deployment-domain>/
```

The legacy `/health/backend` URL redirects to `/health`. The three-hour mock
timer does not require a three-hour request: the browser and database retain
exam state while API calls remain short.

An unauthenticated `/api/v1/auth/me` response intentionally reports guest state
with status `200`. After sign-in, confirm that `/auth/me` reports the Firebase
user, practice progress survives a refresh, and logout clears the
`gatepath_session` cookie. Follow the
[deployment smoke-check procedure](docs/firebase-vercel.md#7-smoke-check-the-deployment)
for the complete sequence.

### Preview and plan safety

- Never expose the production `DATABASE_URL` to Preview. Use Neon database
  branches, or a completely separate preview database.
- A feature branch that changes migrations must be bootstrapped only against
  its matching preview branch before testing.
- Keep all automatic startup-write flags disabled. Vercel instances may start
  concurrently and use a read-only filesystem apart from temporary storage.
- Use a separate Firebase project for Preview when account separation is
  required. Otherwise authorize only selected preview hostnames and leave
  Firebase disabled on throwaway previews; guest testing continues to work.
- Keep Preview on `USER_STATE_BACKEND=postgres`, or give it a separate Firebase
  project with its own `(default)` database. The checked-in deny-all rules and
  index exemptions deliberately support only the `gatepath` collection prefix;
  never point arbitrary previews at the production learner-state collections.
- Vercel Hobby is suitable for personal, non-commercial preparation subject
  to its function and bandwidth quotas. A public or commercial service must
  follow the current [Vercel plan terms](https://vercel.com/docs/plans/hobby)
  and Neon limits.

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
python scripts/bootstrap_database.py
uvicorn app.main:app --reload --port 8000
```

The default local database is SQLite. Copy `backend/.env.example` to `backend/.env` to override settings.
After the explicit bootstrap, set `AUTO_BOOTSTRAP_ON_STARTUP=false` in that
local file to avoid repeating the idempotent import on every Uvicorn reload.
Firebase remains optional locally. For account testing, set
`FIREBASE_AUTH_ENABLED=true`, `FIREBASE_PROJECT_ID`, and either the server-only
`FIREBASE_SERVICE_ACCOUNT_JSON` or a trusted
`GOOGLE_APPLICATION_CREDENTIALS` file path.

### Frontend

```bash
npm ci
npm run dev
```

The frontend runs at http://localhost:3000 and proxies `/api/v1/*` to the
backend. Set `BACKEND_INTERNAL_URL` when the API is on another internal host.
The supported browser deployment is same-origin through this proxy (or
same-site subdomains); unrelated frontend/API domains are not supported by the
default `SameSite=Lax` identity cookies. Add the public
`NEXT_PUBLIC_FIREBASE_*` values to an ignored `.env.local` file to enable the
sign-in UI. Analytics remains disabled when its optional measurement ID is
absent.

## Verification

```bash
cd backend
pytest
python scripts/validate_pyq_consolidation.py
python scripts/validate_question_bank.py
python scripts/check_learning_originality.py path/to/reference.pdf

cd ..
npm run typecheck
npm run build
```

The frontend build validates the learning library as a curriculum: all 64
canonical chapter IDs must be present exactly once, and every chapter must meet
minimum depth requirements for objectives, concept explanations, examples,
formula or method cards, and checkpoints. The optional originality audit flags
long phrase overlap by file and line without printing copyrighted reference
text.

To validate the deployment definition without starting containers:

```bash
docker compose config
```

## Question-bank and PYQ pipeline

`backend/data/question_bank.json` is the authoritative local updater. The
explicit database bootstrap validates and imports it idempotently, records a
checksum audit, reactivates questions when an older bank is deliberately
restored, and retires omitted import-managed rows without breaking historical
attempts. Application cold starts do not mutate the bank or test catalog.

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
docs/                 Firebase, Vercel, and operational deployment guidance
public/              Frontend static assets
firebase.json         Firestore deployment and local emulator configuration
firestore.rules       Deny-all browser access; FastAPI Admin access only
firestore.indexes.json Firestore index exemptions for large learner-state fields
Dockerfile           Production frontend image
docker-compose.yml   Frontend, API, and PostgreSQL stack
vercel.json           One-project Next.js and FastAPI Vercel Services routing
```

## Authoritative sources

- [GATE 2027 question paper pattern](https://gate2027.iitm.ac.in/question_paper_pattern)
- [GATE 2027 CS syllabus](https://gate2027.iitm.ac.in/static/doc/GATE2027_Syllabus/CS_GATE2027_Syllabus.pdf)
- [GATE 2027 syllabus index](https://gate2027.iitm.ac.in/exam_papers_and_syllabus)
- [Official previous papers and answer keys](https://gate2027.iitm.ac.in/download)

GatePath is an independent preparation tool and is not affiliated with IIT Madras or the GATE organizing committee.
