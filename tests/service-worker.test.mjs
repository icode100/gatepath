import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

import { loadTypeScriptModule } from "./load-typescript-module.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SOURCE = readFileSync(resolve(ROOT, "public", "sw.js"), "utf8");
const ORIGIN = "https://gatepath.vercel.app";
const MANIFEST = loadTypeScriptModule("app/manifest.ts").default();
const QUESTION_ASSET_MANIFEST = JSON.parse(
  readFileSync(
    resolve(ROOT, "backend", "data", "pyq_question_assets.json"),
    "utf8",
  ),
);
const PROMOTED_QUESTION_ASSETS = QUESTION_ASSET_MANIFEST.assets.map(
  (asset) => asset.public_url,
);
const PRECACHE_NAME = "gatepath-pwa-precache-v5";
const QUESTION_ASSET_CACHE_NAME =
  `gatepath-pwa-question-assets-v${QUESTION_ASSET_MANIFEST.artifact_sha256.slice(0, 12)}`;

const requestKey = (request) =>
  new URL(typeof request === "string" ? request : request.url, ORIGIN).href;

class MemoryCache {
  constructor() {
    this.entries = new Map();
  }

  async addAll(urls) {
    for (const url of urls) {
      const contentType = url.endsWith(".html")
        ? "text/html"
        : url.endsWith(".svg")
          ? "image/svg+xml"
          : "image/png";
      await this.put(
        url,
        new Response(`precache:${url}`, {
          headers: { "Content-Type": contentType },
        }),
      );
    }
  }

  async match(request) {
    return this.entries.get(requestKey(request))?.clone();
  }

  async put(request, response) {
    this.entries.set(requestKey(request), response.clone());
  }

  async keys() {
    return [...this.entries.keys()].map((url) => new Request(url));
  }

  async delete(request) {
    return this.entries.delete(requestKey(request));
  }
}

function createHarness() {
  const listeners = new Map();
  const stores = new Map();
  let fetchImplementation = async (request) => {
    const pathname = new URL(requestKey(request)).pathname;
    return new Response("asset", {
      headers: {
        "Cache-Control": "public, max-age=31536000, immutable",
        "Content-Type": pathname.startsWith("/question-assets/pyq/")
          ? "image/png"
          : "application/javascript",
      },
    });
  };
  let claimCount = 0;

  const cacheStorage = {
    async open(name) {
      if (!stores.has(name)) stores.set(name, new MemoryCache());
      return stores.get(name);
    },
    async keys() {
      return [...stores.keys()];
    },
    async delete(name) {
      return stores.delete(name);
    },
  };

  const worker = {
    location: { origin: ORIGIN },
    clients: {
      async claim() {
        claimCount += 1;
      },
    },
    skipWaiting() {},
    addEventListener(type, listener) {
      listeners.set(type, listener);
    },
  };

  vm.runInNewContext(SOURCE, {
    caches: cacheStorage,
    console,
    fetch: (...args) => fetchImplementation(...args),
    Headers,
    Promise,
    Request,
    Response,
    self: worker,
    Set,
    URL,
  });

  return {
    cacheStorage,
    get claimCount() {
      return claimCount;
    },
    listeners,
    setFetch(implementation) {
      fetchImplementation = implementation;
    },
    stores,
  };
}

function dispatchFetch(harness, request) {
  let responsePromise = null;
  harness.listeners.get("fetch")({
    request,
    respondWith(response) {
      responsePromise = Promise.resolve(response);
    },
  });
  return responsePromise;
}

test("installation precaches every manifest icon and the offline shell", async () => {
  const harness = createHarness();
  let installation;
  harness.listeners.get("install")({
    waitUntil(promise) {
      installation = promise;
    },
  });
  assert.ok(installation, "service worker install handler must schedule precaching");
  await installation;

  const precache = harness.stores.get(PRECACHE_NAME);
  assert.ok(precache, "installation must open the GatePath precache");
  for (const icon of MANIFEST.icons ?? []) {
    assert.ok(await precache.match(icon.src), `${icon.src} is missing from the precache`);
  }
  assert.ok(await precache.match("/offline.html"));
  assert.ok(await precache.match("/apple-touch-icon.png"));

  const questionAssets = harness.stores.get(QUESTION_ASSET_CACHE_NAME);
  assert.ok(questionAssets, "installation must open the promoted PNG cache");
  assert.equal((await questionAssets.keys()).length, PROMOTED_QUESTION_ASSETS.length);
  for (const pathname of PROMOTED_QUESTION_ASSETS) {
    assert.ok(
      await questionAssets.match(pathname),
      `${pathname} is missing from the offline question cache`,
    );
  }
});

test("question asset cache is exactly the checksum-bound nine-file promotion allowlist", () => {
  assert.equal(QUESTION_ASSET_MANIFEST.counts.unique_png_files, 9);
  assert.equal(PROMOTED_QUESTION_ASSETS.length, 9);
  assert.match(
    SOURCE,
    new RegExp(`question-assets-v${QUESTION_ASSET_MANIFEST.artifact_sha256.slice(0, 12)}`),
  );
  const listed = [...SOURCE.matchAll(/"(\/question-assets\/pyq\/[^"?]+\.png)"/g)]
    .map((match) => match[1]);
  assert.deepEqual(new Set(listed), new Set(PROMOTED_QUESTION_ASSETS));
  assert.equal(listed.length, PROMOTED_QUESTION_ASSETS.length);
});

test("strictly bypasses API, auth, mutation, cross-origin and RSC requests", () => {
  const harness = createHarness();
  const bypassed = [
    new Request(`${ORIGIN}/api/v1/subjects`),
    new Request(`${ORIGIN}/api/v1/auth/me`),
    new Request(`${ORIGIN}/health`),
    new Request(`${ORIGIN}/__/auth/handler`),
    new Request(`${ORIGIN}/_next/static/chunks/app.js`, { method: "POST" }),
    new Request("https://identitytoolkit.googleapis.com/v1/accounts:signIn"),
    new Request(`${ORIGIN}/_next/static/chunks/app.js`, {
      headers: { Authorization: "Bearer secret" },
    }),
    new Request(`${ORIGIN}/_next/static/chunks/app.js`, {
      headers: { Range: "bytes=0-20" },
    }),
    new Request(`${ORIGIN}/_next/static/chunks/app.js`, {
      headers: { RSC: "1" },
    }),
    new Request(`${ORIGIN}/_next/static/chunks/app.js`, {
      headers: { "Next-Router-Prefetch": "1" },
    }),
    new Request(`${ORIGIN}/_next/static/chunks/app.js`, {
      cache: "no-store",
    }),
    new Request(`${ORIGIN}/_next/static/chunks/app.js?_rsc=release`),
  ];

  for (const request of bypassed) {
    assert.equal(dispatchFetch(harness, request), null, request.url);
  }
});

test("bounds the runtime Next static cache and rejects query-key amplification", async () => {
  const harness = createHarness();

  for (let index = 0; index < 140; index += 1) {
    const request = new Request(
      `${ORIGIN}/_next/static/chunks/release-${index}.js`,
    );
    const response = dispatchFetch(harness, request);
    assert.ok(response);
    assert.equal((await response).status, 200);
  }

  const runtime = harness.stores.get("gatepath-pwa-next-static-v1");
  assert.ok(runtime);
  const keys = await runtime.keys();
  assert.equal(keys.length, 128);
  assert.equal(
    await runtime.match(`${ORIGIN}/_next/static/chunks/release-0.js`),
    undefined,
  );
  assert.ok(
    await runtime.match(`${ORIGIN}/_next/static/chunks/release-139.js`),
  );

  const amplified = new Request(
    `${ORIGIN}/_next/static/chunks/release-139.js?cache-key=another`,
  );
  assert.equal(dispatchFetch(harness, amplified), null);
  assert.equal(
    dispatchFetch(harness, new Request(`${ORIGIN}/icon.svg?cache-key=another`)),
    null,
  );
});

test("promoted PNGs use a cache-first strategy while unlisted, queried, and cross-origin images bypass", async () => {
  const harness = createHarness();
  const pathname = PROMOTED_QUESTION_ASSETS[0];
  const request = new Request(`${ORIGIN}${pathname}`);
  let fetches = 0;
  harness.setFetch(async () => {
    fetches += 1;
    return new Response("verified png", {
      headers: {
        "Cache-Control": "public, max-age=31536000, immutable",
        "Content-Type": "image/png",
      },
    });
  });

  const first = dispatchFetch(harness, request);
  assert.ok(first);
  assert.equal(await (await first).text(), "verified png");
  const second = dispatchFetch(harness, request);
  assert.ok(second);
  assert.equal(await (await second).text(), "verified png");
  assert.equal(fetches, 1, "the second immutable request must come from cache");

  const cache = harness.stores.get(QUESTION_ASSET_CACHE_NAME);
  assert.ok(cache);
  assert.equal((await cache.keys()).length, 1);
  assert.equal(
    dispatchFetch(harness, new Request(`${ORIGIN}${pathname}?variant=2`)),
    null,
  );
  assert.equal(
    dispatchFetch(
      harness,
      new Request(
        `${ORIGIN}/question-assets/pyq/gate-cs-2025-set-1/${"f".repeat(64)}.png`,
      ),
    ),
    null,
  );
  assert.equal(
    dispatchFetch(
      harness,
      new Request(`https://cdn.example${pathname}`),
    ),
    null,
  );
});

test("question image cache rejects non-PNG, unsuccessful, private, and opaque responses", async () => {
  const cases = [
    new Response("html", { headers: { "Content-Type": "text/html" } }),
    new Response("missing", {
      status: 404,
      headers: { "Content-Type": "image/png" },
    }),
    new Response("private", {
      headers: {
        "Cache-Control": "private, no-store",
        "Content-Type": "image/png",
      },
    }),
    {
      ok: true,
      redirected: false,
      type: "opaque",
      headers: new Headers({ "Content-Type": "image/png" }),
    },
  ];

  for (const unsafe of cases) {
    const harness = createHarness();
    const request = new Request(`${ORIGIN}${PROMOTED_QUESTION_ASSETS[0]}`);
    harness.setFetch(async () => unsafe);
    const response = dispatchFetch(harness, request);
    assert.ok(response);
    assert.equal(await response, unsafe);
    const cache = harness.stores.get(QUESTION_ASSET_CACHE_NAME);
    assert.ok(cache);
    assert.equal(await cache.match(request), undefined);
  }
});

test("does not retain private or no-store static responses", async () => {
  const harness = createHarness();
  harness.setFetch(async () =>
    new Response("sensitive", {
      headers: {
        "Cache-Control": "private, no-store",
        "Content-Type": "application/javascript",
      },
    }),
  );
  const request = new Request(`${ORIGIN}/_next/static/chunks/private.js`);
  const response = dispatchFetch(harness, request);
  assert.ok(response);
  await response;

  const runtime = harness.stores.get("gatepath-pwa-next-static-v1");
  assert.ok(runtime);
  assert.equal(await runtime.match(request), undefined);
});

test("activation removes only obsolete GatePath caches", async () => {
  const harness = createHarness();
  await harness.cacheStorage.open(PRECACHE_NAME);
  const questionAssets = await harness.cacheStorage.open(QUESTION_ASSET_CACHE_NAME);
  await questionAssets.put(
    `${ORIGIN}/question-assets/pyq/unapproved.png`,
    new Response("unapproved", { headers: { "Content-Type": "image/png" } }),
  );
  await harness.cacheStorage.open("gatepath-pwa-precache-v3");
  await harness.cacheStorage.open("gatepath-pwa-precache-v2");
  await harness.cacheStorage.open("gatepath-pwa-precache-v1");
  await harness.cacheStorage.open("gatepath-pwa-next-static-v1");
  await harness.cacheStorage.open("gatepath-pwa-question-assets-vobsolete");
  await harness.cacheStorage.open("gatepath-pwa-static-v0");
  await harness.cacheStorage.open("firebase-unrelated-cache");

  let activation;
  harness.listeners.get("activate")({
    waitUntil(promise) {
      activation = promise;
    },
  });
  await activation;

  assert.deepEqual(
    new Set(await harness.cacheStorage.keys()),
    new Set([
      PRECACHE_NAME,
      "gatepath-pwa-next-static-v1",
      QUESTION_ASSET_CACHE_NAME,
      "firebase-unrelated-cache",
    ]),
  );
  assert.equal((await questionAssets.keys()).length, 0);
  assert.equal(harness.claimCount, 1);
});

test("offline navigations use only the generic precached fallback", async () => {
  const harness = createHarness();
  const precache = await harness.cacheStorage.open(PRECACHE_NAME);
  await precache.put(
    "/offline.html",
    new Response("GatePath is offline", {
      headers: { "Content-Type": "text/html" },
    }),
  );
  harness.setFetch(async () => {
    throw new TypeError("offline");
  });

  const navigation = {
    headers: new Headers(),
    method: "GET",
    mode: "navigate",
    url: `${ORIGIN}/roadmap`,
  };
  const response = dispatchFetch(harness, navigation);
  assert.ok(response);
  assert.equal(await (await response).text(), "GatePath is offline");
});
