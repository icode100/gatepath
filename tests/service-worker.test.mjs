import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SOURCE = readFileSync(resolve(ROOT, "public", "sw.js"), "utf8");
const ORIGIN = "https://gatepath.vercel.app";

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
  let fetchImplementation = async () =>
    new Response("asset", {
      headers: { "Content-Type": "application/javascript" },
    });
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
  await harness.cacheStorage.open("gatepath-pwa-precache-v1");
  await harness.cacheStorage.open("gatepath-pwa-next-static-v1");
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
      "gatepath-pwa-precache-v1",
      "gatepath-pwa-next-static-v1",
      "firebase-unrelated-cache",
    ]),
  );
  assert.equal(harness.claimCount, 1);
});

test("offline navigations use only the generic precached fallback", async () => {
  const harness = createHarness();
  const precache = await harness.cacheStorage.open("gatepath-pwa-precache-v1");
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
