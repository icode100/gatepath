const CACHE_PREFIX = "gatepath-pwa-";
const PRECACHE_VERSION = `${CACHE_PREFIX}precache-v5`;
const RUNTIME_STATIC_VERSION = `${CACHE_PREFIX}next-static-v1`;
// This suffix is the first 12 characters of the checksum-bound
// backend/data/pyq_question_assets.json artifact. A changed promotion set
// necessarily creates a new cache and activation removes the old one.
const QUESTION_ASSET_CACHE_VERSION = `${CACHE_PREFIX}question-assets-vca96d326bccf`;
const CURRENT_CACHES = new Set([
  PRECACHE_VERSION,
  RUNTIME_STATIC_VERSION,
  QUESTION_ASSET_CACHE_VERSION,
]);
const MAX_RUNTIME_STATIC_ENTRIES = 128;
const OFFLINE_URL = "/offline.html";
const STATIC_ASSETS = [
  OFFLINE_URL,
  "/icon.svg",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-maskable-512.png",
  "/icons/icon-monochrome-512.png",
  "/apple-touch-icon.png",
];
const PROMOTED_QUESTION_ASSETS = Object.freeze([
  "/question-assets/pyq/gate-cs-2024-set-1/0dc6c5f61a39fb52718b5d9a338863170958ceb73d5cdb447cd6f22613c315b4.png",
  "/question-assets/pyq/gate-cs-2024-set-1/b820573c205599853769976192f377b90d1bdd82be5d2d4496301692fd08c6bc.png",
  "/question-assets/pyq/gate-cs-2024-set-2/1304642d3bd784a2c674c912cd59341bec46379c65b7951fb811495c86a73788.png",
  "/question-assets/pyq/gate-cs-2024-set-2/bf218e84811bcd38a961418d4204581788853c7d5125c6ca3c3332154870c98f.png",
  "/question-assets/pyq/gate-cs-2025-set-1/585602e4b598f8757f539e142c36ad739225826a00636558563feb3775a55810.png",
  "/question-assets/pyq/gate-cs-2025-set-1/fd5ea7730d1dd13ab637e5e7fbc857a2e05c96d8fb3963a9f4aca8988f07dea6.png",
  "/question-assets/pyq/gate-cs-2025-set-1/181f7eaa790a1dfa8e4f4f1c67ba0c2227efcd748ab781b95d4eac9a090db143.png",
  "/question-assets/pyq/gate-cs-2025-set-1/c3d629de9303f6cc6fb9b7c1ea88a3ecb50737c7537d3a8166d0c46c0175ad0f.png",
  "/question-assets/pyq/gate-cs-2025-set-2/5f6fc50c6711df94a2198aca6853c5f33d95e1a0eb2a5a3afe84e0d7c0c85cc4.png",
]);
const PROMOTED_QUESTION_ASSET_SET = new Set(PROMOTED_QUESTION_ASSETS);

const NEVER_INTERCEPT = [
  "/api/",
  "/health",
  "/internal/",
  "/docs",
  "/redoc",
  "/openapi.json",
  "/__/auth/",
];

const cacheableQuestionAssetResponse = (response) => {
  if (!response.ok || response.redirected || response.type === "opaque") return false;
  const cacheControl = response.headers.get("cache-control") ?? "";
  if (/\b(?:private|no-store)\b/i.test(cacheControl)) return false;
  const contentType = response.headers.get("content-type") ?? "";
  return /^image\/png(?:\s*;|\s*$)/i.test(contentType);
};

const questionAssetRequest = (pathname) =>
  new Request(new URL(pathname, self.location.origin), {
    cache: "reload",
    credentials: "same-origin",
  });

const precacheQuestionAssets = async () => {
  const cache = await caches.open(QUESTION_ASSET_CACHE_VERSION);
  await Promise.all(
    PROMOTED_QUESTION_ASSETS.map(async (pathname) => {
      const request = questionAssetRequest(pathname);
      const response = await fetch(request);
      if (!cacheableQuestionAssetResponse(response)) {
        throw new TypeError(`Refusing unsafe promoted question asset: ${pathname}`);
      }
      await cache.put(request, response.clone());
    }),
  );
};

self.addEventListener("install", (event) => {
  event.waitUntil(
    Promise.all([
      caches.open(PRECACHE_VERSION).then((cache) => cache.addAll(STATIC_ASSETS)),
      precacheQuestionAssets(),
    ]),
  );
});

const pruneQuestionAssetCache = async () => {
  const cache = await caches.open(QUESTION_ASSET_CACHE_VERSION);
  const requests = await cache.keys();
  await Promise.all(
    requests
      .filter((request) => {
        const url = new URL(request.url);
        return (
          url.origin !== self.location.origin ||
          url.search !== "" ||
          !PROMOTED_QUESTION_ASSET_SET.has(url.pathname)
        );
      })
      .map((request) => cache.delete(request)),
  );
};

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(CACHE_PREFIX) && !CURRENT_CACHES.has(key))
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => pruneQuestionAssetCache())
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") self.skipWaiting();
});

const isPrivateRequest = (request, url) =>
  request.method !== "GET" ||
  url.origin !== self.location.origin ||
  request.cache === "no-store" ||
  request.headers.has("authorization") ||
  request.headers.has("range") ||
  request.headers.has("rsc") ||
  request.headers.has("next-router-prefetch") ||
  url.searchParams.has("_rsc") ||
  NEVER_INTERCEPT.some((prefix) => url.pathname === prefix || url.pathname.startsWith(prefix));

const cacheableStaticResponse = (response) => {
  if (!response.ok || response.redirected || response.type === "opaque") return false;
  const cacheControl = response.headers.get("cache-control") ?? "";
  if (/\b(?:private|no-store)\b/i.test(cacheControl)) return false;
  const contentType = response.headers.get("content-type") ?? "";
  return /javascript|text\/css|font|image\//i.test(contentType);
};

const trimRuntimeStaticCache = async (cache) => {
  const requests = await cache.keys();
  const overflow = requests.length - MAX_RUNTIME_STATIC_ENTRIES;
  if (overflow <= 0) return;
  await Promise.all(requests.slice(0, overflow).map((request) => cache.delete(request)));
};

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (isPrivateRequest(request, url)) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(async () => {
        const cache = await caches.open(PRECACHE_VERSION);
        return (await cache.match(OFFLINE_URL)) ?? Response.error();
      }),
    );
    return;
  }

  const isNextStatic =
    url.pathname.startsWith("/_next/static/") && url.search === "";
  const isAllowedPublicAsset =
    STATIC_ASSETS.includes(url.pathname) && url.search === "";
  const isPromotedQuestionAsset =
    url.search === "" && PROMOTED_QUESTION_ASSET_SET.has(url.pathname);
  if (!isNextStatic && !isAllowedPublicAsset && !isPromotedQuestionAsset) return;

  event.respondWith(
    caches
      .open(
        isNextStatic
          ? RUNTIME_STATIC_VERSION
          : isPromotedQuestionAsset
            ? QUESTION_ASSET_CACHE_VERSION
            : PRECACHE_VERSION,
      )
      .then(async (cache) => {
        const cached = await cache.match(request);
        if (cached) return cached;
        const response = await fetch(request);
        const cacheable = isPromotedQuestionAsset
          ? cacheableQuestionAssetResponse(response)
          : cacheableStaticResponse(response);
        if (cacheable) {
          await cache.put(request, response.clone());
          if (isNextStatic) await trimRuntimeStaticCache(cache);
        }
        return response;
      }),
  );
});
