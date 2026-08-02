# Firebase authentication and Analytics on Vercel

Gatepath uses Firebase for account sign-in and optional product telemetry. It
does **not** replace PostgreSQL:

- Neon PostgreSQL remains the source of truth for the syllabus, questions,
  tests, attempts, progress, and topic-mastery analytics.
- Firebase Authentication supplies a stable user identity across devices.
- Google Analytics for Firebase is optional browser-side product telemetry.
  It does not store or calculate Gatepath learning analytics.

The browser signs in with the Firebase Web SDK and exchanges its short-lived ID
token for a Firebase session cookie issued by FastAPI. The Admin service-account
credential is used only by the backend.

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

## 2. Create the Admin credential

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

## 3. Add Vercel environment variables

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

Keep the existing guest identity settings too. Firebase is additive: when it is
disabled, the full application remains usable with the signed guest identity.
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

## 4. Configure Analytics safely

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
- keep detailed answer history and mastery calculations in Neon, where
  Gatepath's application authorization applies.

Firebase documents a limit of 500 distinct Analytics event types for standard
Analytics, and event names are case-sensitive. Prefer a small fixed vocabulary
such as sign-in, practice-started, test-started, and test-completed rather than
embedding course, topic, or user data in event names.

## 5. Bootstrap Neon and deploy

Firebase setup does not initialize the application database. Neon remains a
separate required dependency.

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

3. In Vercel, redeploy the latest `main` commit after all Firebase and Neon
   variables have been saved.
4. Use the production alias for the first sign-in test. Add a custom domain to
   Firebase Authorized domains before moving production traffic to it.

## 6. Smoke-check the deployment

First verify routing, FastAPI, and Neon:

```text
GET https://<deployment-domain>/
GET https://<deployment-domain>/health
GET https://<deployment-domain>/openapi.json
GET https://<deployment-domain>/api/v1/tests/catalog
```

The root, health, OpenAPI, and catalog requests should return `200`; the health
body should report the database as `ok`.

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
   topic-mastery views update. These records should persist in Neon after a
   refresh and a new Vercel function instance.
7. Log out through `POST /api/v1/auth/logout` with the current CSRF token.
   Confirm the session cookie is cleared and `/auth/me` returns guest state.
8. If Analytics is enabled and consented, use Firebase Analytics DebugView to
   confirm only the intended product events are received. Do not use the
   learning dashboard as an Analytics verification tool; it reads Neon.

If all FastAPI paths return `FUNCTION_INVOCATION_FAILED`, inspect the backend
function logs first. Typical configuration causes are malformed
`FIREBASE_SERVICE_ACCOUNT_JSON`, a `FIREBASE_PROJECT_ID` mismatch, or a missing
Neon URL. Temporarily setting `FIREBASE_AUTH_ENABLED=false` can distinguish an
Admin initialization problem from a database/routing problem while preserving
guest access; do not treat that as the final production configuration.

## Authoritative Firebase references

- [Get started with Firebase Authentication on websites](https://firebase.google.com/docs/auth/web/start)
- [Authenticate using Google with JavaScript](https://firebase.google.com/docs/auth/web/google-signin)
- [Manage Firebase session cookies](https://firebase.google.com/docs/auth/admin/manage-cookies)
- [Initialize the Firebase Admin SDK outside Google](https://firebase.google.com/docs/admin/setup)
- [Manage Firebase Authentication authorized domains](https://firebase.google.com/support/faq)
- [Get started with Google Analytics for Web](https://firebase.google.com/docs/analytics/web/get-started)
- [Firebase Analytics JavaScript API and environment checks](https://firebase.google.com/docs/reference/js/analytics)
- [Firebase API-key security guidance](https://firebase.google.com/docs/projects/api-keys)
