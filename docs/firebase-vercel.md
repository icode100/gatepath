# Firebase authentication, Firestore data, and Analytics on Vercel

Gatepath uses Firebase for account sign-in, production learner-state storage,
an optional immutable question catalog, and optional product telemetry:

- Neon PostgreSQL is the default catalog and rollback source. A separately
  verified publication can move static runtime reads to Firestore.
- Firestore stores mutable sessions, attempts, progress evidence, and
  topic-mastery analytics when `USER_STATE_BACKEND=firestore`.
- Firebase Authentication supplies a stable user identity across devices.
- Google Analytics for Firebase is optional browser-side product telemetry.
  It does not store or calculate Gatepath learning analytics.

The browser signs in with the Firebase Web SDK and exchanges its short-lived ID
token for a Firebase session cookie issued by FastAPI. The Admin service-account
credential is reused by FastAPI for both Authentication and Firestore. The
browser never connects to Firestore directly.

## 1. Create the Firebase web app

1. Open the [Firebase Console](https://console.firebase.google.com/) and create
   a project, or open the project that will own Gatepath Authentication.
2. In **Project overview**, select **Add app → Web** (`</>`), name it
   `gatepath-web`, and register it. Firebase Hosting is not required because the
   application remains on Vercel.
3. Copy the Web SDK configuration shown under **Project settings → General →
   Your apps → SDK setup and configuration → Config**. Its `apiKey`,
   `authDomain`, `projectId`, `appId`, and optional `measurementId` are public
   application identifiers, not Admin credentials.
4. Open **Build → Authentication → Get started → Sign-in method**. Enable
   **Email/Password** and **Google**, then choose the Google provider's public
   support email.
5. Open **Authentication → Settings → Authorized domains** and add:

   - `gatepath.vercel.app` for the current production alias;
   - the final custom domain, when one is attached to Vercel;
   - `localhost` only when local Firebase sign-in is required.

Firebase projects created after April 28, 2025 do not authorize `localhost` by
default. Do not leave it authorized solely for production. Vercel creates a
different hostname for each preview deployment; either add a deliberately
selected preview hostname, use a stable preview/custom hostname, or test those
previews as a guest. Avoid continuously authorizing throwaway preview hosts.

Google popup sign-in works with the normal Firebase `authDomain`. If the
application is changed to use `signInWithRedirect`, follow Firebase's
[redirect guidance for non-Firebase hosting](https://firebase.google.com/docs/auth/web/redirect-best-practices)
to account for browsers that block third-party storage.

## 2. Create the Firestore database and deploy server-only rules

1. In the Firebase Console, open **Build → Firestore Database → Create
   database**.
2. Choose the **Standard** edition and keep the database ID `(default)`. The
   checked-in deployment configuration and production default target this ID.
3. Choose a location near both the Vercel FastAPI functions and the Neon
   catalog database. Cross-region reads add latency to every session and
   analytics request, and the database location is difficult to change later.
4. From a trusted workstation with the Firebase CLI authenticated, deploy the
   checked-in rules and index settings:

   ```powershell
   firebase deploy --only firestore:rules,firestore:indexes --project <firebase-project-id>
   ```

[`firestore.rules`](../firestore.rules) denies every browser read and write.
This is intentional: all learner-state access goes through FastAPI, and the
Firebase Admin SDK bypasses Firestore Security Rules. Do not add Firestore
browser initialization or permissive client rules. [`firestore.indexes.json`](../firestore.indexes.json)
has no composite indexes and exempts large learner-state, immutable shard,
question, alias, note, and archive payloads from automatic single-field
indexing.

The checked-in exemptions name collections using the fixed `gatepath` prefix,
and the deployment config targets `(default)`. The backend deliberately rejects
other prefixes/database IDs so it cannot silently write large documents outside
the protected index/rules target. Use a separate Firebase project—not a renamed
collection prefix or database—for an isolated Preview environment.

## 3. Create the Admin credential

1. In Firebase, open **Project settings → Service accounts → Firebase Admin
   SDK**.
2. Select **Generate new private key**, confirm, and download the JSON file.
3. Treat this file as a production secret. Do not copy it into the repository,
   a Docker image, a browser-visible variable, a ticket, or build output.
4. Serialize the complete JSON object as one line for the Vercel secret. Keep
   the `private_key` value's `\n` escape sequences intact. Paste it directly
   into Vercel rather than passing it on a shell command line.
5. Delete the downloaded local copy after the Vercel secret is configured, or
   keep it only in an approved secret manager. If it is exposed, delete that
   key in Google Cloud IAM immediately, generate a replacement, update Vercel,
   and redeploy.

The backend also supports Application Default Credentials through
`GOOGLE_APPLICATION_CREDENTIALS` when `FIREBASE_SERVICE_ACCOUNT_JSON` is unset.
That file-path workflow is useful for trusted local/server environments. On
Vercel, use the encrypted `FIREBASE_SERVICE_ACCOUNT_JSON` value; never create a
`NEXT_PUBLIC_` version of it.

## 4. Add Vercel environment variables

Open the Gatepath project in Vercel and go to **Settings → Environment
Variables**. Add these Firebase Web SDK values to Production and to any Preview
environment where sign-in should work:

| Variable | Firebase configuration field | Required |
| --- | --- | --- |
| `NEXT_PUBLIC_FIREBASE_API_KEY` | `apiKey` | yes |
| `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN` | `authDomain` | yes |
| `NEXT_PUBLIC_FIREBASE_PROJECT_ID` | `projectId` | yes |
| `NEXT_PUBLIC_FIREBASE_APP_ID` | `appId` | yes |
| `NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID` | `measurementId` | only for Analytics |
| `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID` | `messagingSenderId` | optional |

Add the following backend values. The service-account JSON is server-only and
must be marked **Sensitive** in Vercel:

| Variable | Production value | Purpose |
| --- | --- | --- |
| `FIREBASE_AUTH_ENABLED` | `true` | Enables ID-token exchange and Firebase sessions |
| `FIREBASE_PROJECT_ID` | Same Firebase `projectId` | Pins token verification to the intended project |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Complete one-line service-account JSON | Admin SDK credential; server-only secret |
| `FIREBASE_SESSION_COOKIE_NAME` | `gatepath_session` | HttpOnly authenticated-session cookie |
| `FIREBASE_CSRF_COOKIE_NAME` | `gatepath_csrf` | Double-submit CSRF cookie |
| `FIREBASE_SESSION_MAX_AGE_SECONDS` | `432000` | Five-day session; allowed range is 300–1209600 |
| `FIREBASE_RECENT_AUTH_SECONDS` | `300` | Requires sign-in within five minutes before exchange |
| `FIREBASE_CHECK_REVOKED` | `false` | Avoids a remote revocation lookup on every authenticated API call |
| `USER_STATE_BACKEND` | `firestore` | Uses Firestore for mutable learner state; `postgres` is the default and rollback value |
| `USER_STATE_MAINTENANCE` | `false` | Blocks learner-state access during the brief migration window |
| `QUESTION_CATALOG_BACKEND` | `firestore` after catalog verification and learner-state cutover | Selects immutable Firestore catalog shards; requires `USER_STATE_BACKEND=firestore`; `postgres` is the rollback value |
| `QUESTION_CATALOG_MAINTENANCE` | `false` | Blocks catalog access while deliberately changing releases |
| `FIRESTORE_CATALOG_CACHE_SECONDS` | `300` | Bounds server-side immutable-shard cache refreshes |
| `FIRESTORE_DATABASE_ID` | `(default)` | Firestore database selected by the backend |
| `FIRESTORE_COLLECTION_PREFIX` | `gatepath` | Prefix for server-owned learner-state collections |

Keep the existing guest identity settings too. Firebase is additive: when it is
disabled, the full application remains usable with the signed guest identity.
Firestore Admin readiness is checked separately from browser sign-in, so a
maintenance deployment may disable account login while retaining learner-state
storage as long as the Admin credential remains configured.
If a browser presents a Firebase session that cannot be verified during an
Admin outage, public curriculum/catalog requests remain readable but owned
progress, practice, and attempt requests return a temporary error. This avoids
silently splitting an authenticated learner's data into a new guest profile.
Logout still clears the unavailable session and rotates to an isolated guest.
Do not remove `ANONYMOUS_IDENTITY_SECRET` from a hosted deployment.

Session-cookie signatures and expiry are verified on every authenticated
request. The initial ID-token exchange also performs Firebase's remote
revocation check. Setting `FIREBASE_CHECK_REVOKED=true` additionally checks
revocation on every subsequent request, which improves immediate revocation
response at the cost of an extra Firebase lookup, latency, and outage exposure.

Environment values are captured when a Vercel deployment is built. After
adding or changing any variable, redeploy the latest `main` commit. Do not rely
on an already-running deployment to pick up the new value.

## 5. Configure Analytics safely

Analytics is optional. Enable it when creating the Firebase project, or later
under **Project settings → Integrations → Google Analytics**, and make sure the
registered web app has a web data stream and `measurementId`.

Gatepath initializes Analytics lazily in a supported browser only. It does not
initialize Analytics in FastAPI, Node.js, or a Next.js server component. If
`NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID` is absent, cookies are disabled, IndexedDB
is unavailable, or the browser context is unsupported, Analytics safely does
nothing.

Before enabling telemetry publicly:

- publish an appropriate privacy notice and implement any consent behavior
  required for the users and jurisdictions in scope;
- do not use an email address, name, Firebase ID token, or other personally
  identifying value as an Analytics user ID or event parameter;
- use a stable, opaque identifier only if cross-device product telemetry is
  actually required;
- keep detailed answer history and mastery calculations behind FastAPI in the
  selected learner-state backend; do not send them to Google Analytics.

Firebase documents a limit of 500 distinct Analytics event types for standard
Analytics, and event names are case-sensitive. Prefer a small fixed vocabulary
such as sign-in, practice-started, test-started, and test-completed rather than
embedding course, topic, or user data in event names.

## 6. Bootstrap Neon, migrate data, and deploy

Firestore setup does not initialize any application data by itself. Keep Neon
as the runtime source while preparing and independently verifying both copies.

1. Confirm Vercel has the correct Neon `DATABASE_URL` and
   `DATABASE_URL_UNPOOLED` for the target environment. Never give a Preview
   deployment the production database URL.
2. From a trusted checkout, bootstrap the target database once as documented
   in the root README:

   ```powershell
   cd backend
   $env:DATABASE_URL = "<Neon pooled PostgreSQL URL>"
   $env:DATABASE_URL_UNPOOLED = "<Neon direct PostgreSQL URL>"
   .venv\Scripts\python scripts/bootstrap_database.py
   Remove-Item Env:DATABASE_URL
   Remove-Item Env:DATABASE_URL_UNPOOLED
   ```

3. Keep `USER_STATE_BACKEND=postgres` while first deploying a release that
   supports both state backends. Do not switch production yet.
4. From the repository root on a trusted workstation, provide both Neon
   connection variables and the same Firebase Admin variables used by Vercel.
   Run the explicit migration in a brief maintenance window:

   ```powershell
   python backend/scripts/migrate_user_state_to_firestore.py --dry-run
   python backend/scripts/migrate_user_state_to_firestore.py --apply
   python backend/scripts/migrate_user_state_to_firestore.py --verify-only
   ```

   Review the dry-run counts before applying and require verification to pass.
   Never add this command to Vercel's build command, startup path, or a
   serverless cold start.

   The production deployment intentionally exposes no HTTP migration route.
   When Vercel Sensitive variables cannot be read back, create a short-lived
   Firebase Admin credential for a trusted workstation, run the checked-in
   CLI, and revoke that credential immediately after verification. Keep
   `USER_STATE_MAINTENANCE=true` for the complete copy-and-verify window and
   restore it to `false` only when switching production to Firestore.
5. Set Production `USER_STATE_BACKEND=firestore`, keep
   `FIRESTORE_DATABASE_ID=(default)` and
   `FIRESTORE_COLLECTION_PREFIX=gatepath`, then redeploy the latest `main`
   commit. Vercel environment changes do not affect an existing deployment.
6. Use the production alias for the first sign-in test. Add a custom domain to
   Firebase Authorized domains before moving production traffic to it.

The migration does not delete or overwrite legacy Neon user-state rows. To
roll back during the initial validation window, restore
`USER_STATE_BACKEND=postgres` and redeploy; Firestore remains untouched.
Post-cutover attempts written only to Firestore must be reconciled before Neon
can again be treated as current, so keep that validation window short and do
not accept extended traffic on both backends independently.

### Static catalog publication

Publish the static catalog only after the Firestore-capable application release
is deployed. The dry run builds an immutable release containing all 5,163
canonical records, 405 lossless legacy-ID aliases, and a 2,467-question active
runtime projection. The runtime projection is packed into checksum-bound
shards (each at most 600 KiB), preventing thousands of document reads on a
serverless cold start.

The optional first command rewrites only the dedicated
`firestore_legacy_catalog_snapshot.json`. Never replace that output with a PYQ
archive, allowlist, or visibility-plan path.

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

Copy the exact `firestore_target.confirmation` value printed by the dry run.
Use `--expected-current-release none` only when no current pointer exists. For a
later release, supply the exact current release ID. Repointing to a previously
published release is an explicit rollback and also requires `--rollback`. The
transactional compare-and-swap blocks concurrent or stale publishers. Never
delete the current pointer; publish or rollback through this CLI. Remote
modes reject a set `FIRESTORE_EMULATOR_HOST` unless the test-only
`--allow-firestore-emulator` override is deliberately supplied.

Before the `--apply` command, set `DATABASE_URL` to the live target
Neon/PostgreSQL database that matches the frozen legacy snapshot. The apply
preflight deliberately rejects SQLite. The apply step verifies the tracked
`backend/data/firestore_catalog_release_manifest.json`; it does not regenerate
or overwrite that reviewed manifest.

Inspect the dry-run counts and release ID before applying. The publisher writes
new immutable release subcollections, verifies every document and shard hash,
and updates `gatepath_catalog_meta/current` last. Never run it from a Vercel
build, startup, or request. After verification succeeds, confirm Production is
already using `USER_STATE_BACKEND=firestore`, then set
`QUESTION_CATALOG_BACKEND=firestore` and redeploy. The backend rejects a
Firestore catalog paired with PostgreSQL learner state because the relational
attempt schema cannot store the catalog's canonical question IDs. Never switch
learner state back to PostgreSQL while the Firestore catalog remains selected.
Retain Neon during the rollback window; neither flag mutates Firestore.

An emergency catalog read fallback starts by restoring
`QUESTION_CATALOG_BACKEND=postgres`. A full behavioral rollback requires a
maintenance window and deterministic canonical-to-legacy evidence
reconciliation for all 177 active audited questions. Immutable snapshots keep
existing sessions and attempts readable, but PostgreSQL-backed practice
rotation, roadmap, and topic analytics are not exact until reconciliation
finishes.

### Free-tier capacity and retention

This split makes Neon storage independent of account and attempt growth, but it
does not make learner state storage unlimited. Firestore's no-cost quota is
currently one free database per project with 1 GiB stored data, 50,000 document
reads per day, 20,000 writes per day, and 20,000 deletes per day. Check the
[official Firestore quota page](https://firebase.google.com/docs/firestore/quotas)
before a public launch because quotas and billing terms can change.

Gatepath keeps the dashboard projection in one document per learner and
exempts large snapshots, responses, and analytics maps from indexing. A test
submission therefore needs only a small fixed number of document reads/writes;
the main variable storage cost is the immutable session and attempt history.
Monitor Firestore usage in the Firebase Console as the user base grows. TTL is
not enabled by this repository because managed TTL deletes require billing;
add an explicit retention policy before the history approaches the free
storage limit. Small `gatepath_claims` tombstones are intentionally permanent:
they prevent an old signed guest cookie from writing new state after its data
has been linked to an account. Do not include that collection in routine
cleanup.

### Local Firestore emulator

The Firebase CLI configuration includes a Firestore emulator on port `8080`.
Start it from the repository root:

```powershell
firebase emulators:start --only firestore --project demo-gatepath
```

In the backend shell, set `FIRESTORE_EMULATOR_HOST=127.0.0.1:8080`,
`FIREBASE_PROJECT_ID=demo-gatepath`, `FIREBASE_AUTH_ENABLED=false`, and
`USER_STATE_BACKEND=firestore` before starting FastAPI. The local Firestore
adapter uses anonymous emulator credentials; no Admin private key is required.
When FastAPI runs inside Docker, use a hostname reachable from the container
instead of `127.0.0.1`. The Next.js/browser application still talks only to
FastAPI; do not install or initialize the Firestore web client for emulator
testing. Clear the emulator or use a distinct demo project/prefix between test
runs so state does not leak across scenarios.

## 7. Smoke-check the deployment

First verify routing, FastAPI, the selected catalog, and Firestore state access:

```text
GET https://<deployment-domain>/
GET https://<deployment-domain>/health
GET https://<deployment-domain>/openapi.json
GET https://<deployment-domain>/api/v1/tests/catalog
```

The root, health, OpenAPI, and catalog requests should return `200`. With both
backends on Firestore, health reports `database=not_required`,
`question_catalog=ok`, and `user_state=ok`.

Then use a private browser window:

1. Load `/` and confirm the guest curriculum and catalog remain usable.
2. Request `GET /api/v1/auth/csrf`; it should return a CSRF token and set the
   `gatepath_csrf` cookie.
3. Sign in with Email/Password or Google. The browser sends the Firebase ID
   token and matching CSRF value to `POST /api/v1/auth/session`.
4. Confirm the response succeeds and sets `gatepath_session` with `HttpOnly`,
   `Secure`, `SameSite=Lax`, and `Path=/`. The Admin credential and ID token
   must never appear in rendered HTML or browser storage.
5. Refresh the page and request `GET /api/v1/auth/me`; it should return the
   signed-in Firebase account. An unauthenticated request intentionally returns
   a `200` guest state rather than `401`.
6. Start a practice session, submit an answer, and confirm the progress and
   topic-mastery views update. With `USER_STATE_BACKEND=firestore`, these
   records should appear under the prefixed Firestore collections and persist
   after a refresh and a new Vercel function instance. With
   `QUESTION_CATALOG_BACKEND=firestore`, catalog reads must continue to work in
   a test deployment that intentionally omits its Neon URL.
7. Log out through `POST /api/v1/auth/logout` with the current CSRF token.
   Confirm the session cookie is cleared and `/auth/me` returns guest state.
8. If Analytics is enabled and consented, use Firebase Analytics DebugView to
   confirm only the intended product events are received. Do not use the
   learning dashboard as an Analytics verification tool; it reads the
   server-side learner-state backend.

If all FastAPI paths return `FUNCTION_INVOCATION_FAILED`, inspect the backend
function logs first. Typical configuration causes are malformed
`FIREBASE_SERVICE_ACCOUNT_JSON`, a `FIREBASE_PROJECT_ID` mismatch, a missing
Neon URL while either backend still selects `postgres`, a missing `(default)`
Firestore database, or an invalid backend flag. Restore
`QUESTION_CATALOG_BACKEND=postgres` to isolate catalog readiness. Once the
catalog is on PostgreSQL, `USER_STATE_BACKEND=postgres` can separately isolate
learner-state readiness without deleting either store.
Disabling Firebase Authentication is a separate guest-mode diagnostic and is
not a substitute for configuring production Firestore.

## Authoritative Firebase references

- [Get started with Firebase Authentication on websites](https://firebase.google.com/docs/auth/web/start)
- [Authenticate using Google with JavaScript](https://firebase.google.com/docs/auth/web/google-signin)
- [Manage Firebase session cookies](https://firebase.google.com/docs/auth/admin/manage-cookies)
- [Initialize the Firebase Admin SDK outside Google](https://firebase.google.com/docs/admin/setup)
- [Create and manage Firestore databases](https://firebase.google.com/docs/firestore/manage-databases)
- [Securely query data with Firestore Security Rules](https://firebase.google.com/docs/firestore/security/get-started)
- [Firestore emulator](https://firebase.google.com/docs/emulator-suite/connect_firestore)
- [Manage Firestore indexes](https://firebase.google.com/docs/firestore/query-data/indexing)
- [Manage Firebase Authentication authorized domains](https://firebase.google.com/support/faq)
- [Get started with Google Analytics for Web](https://firebase.google.com/docs/analytics/web/get-started)
- [Firebase Analytics JavaScript API and environment checks](https://firebase.google.com/docs/reference/js/analytics)
- [Firebase API-key security guidance](https://firebase.google.com/docs/projects/api-keys)
