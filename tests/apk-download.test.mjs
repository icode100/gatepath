import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const COMPONENT = readFileSync(
  resolve(ROOT, "components", "pwa", "MobileAppSettings.tsx"),
  "utf8",
);
const WORKFLOW = readFileSync(
  resolve(ROOT, ".github", "workflows", "android.yml"),
  "utf8",
);

const RELEASE_TAG = "android-preview-v5";
const RELEASE_ASSET = "gatepath-android.apk";
const RELEASE_CHECKSUM = `${RELEASE_ASSET}.sha256`;
const RELEASE_URL =
  `https://github.com/icode100/gatepath/releases/download/${RELEASE_TAG}/${RELEASE_ASSET}`;

function normalized(source) {
  return source.replace(/\s+/g, " ").trim();
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

test("mobile settings use the immutable Android preview release asset", () => {
  const url = new URL(RELEASE_URL);
  assert.equal(url.protocol, "https:");
  assert.equal(url.hostname, "github.com");
  assert.equal(
    url.pathname,
    `/icode100/gatepath/releases/download/${RELEASE_TAG}/${RELEASE_ASSET}`,
  );

  assert.match(COMPONENT, new RegExp(escapeRegExp(RELEASE_URL)));
  assert.doesNotMatch(
    COMPONENT,
    /github\.com\/icode100\/gatepath\/actions(?:\/|["'])/i,
    "the application must not link to an expiring or authenticated Actions artifact",
  );
  assert.doesNotMatch(
    COMPONENT,
    /github\.com\/icode100\/gatepath\/releases\/latest(?:\/|["'])/i,
    "the preview must remain pinned to its immutable release tag",
  );
});

test("Android preview download is an accessible link with disclosure and analytics", () => {
  const anchor = COMPONENT.match(
    /<a\b[\s\S]*?href=\{ANDROID_PREVIEW_URL\}[\s\S]*?<\/a>/,
  )?.[0];
  assert.ok(anchor, "missing Android preview download anchor");
  assert.match(anchor, /aria-describedby=["']android-preview-description["']/);
  assert.match(anchor, /Download Android preview \(\.apk\)/i);
  assert.match(anchor, /<span\b[^>]*aria-hidden=["']true["'][^>]*>/);

  const source = normalized(COMPONENT);
  assert.match(
    source,
    /<p id=["']android-preview-description["']> Preview v5 · Debug-signed\. Uninstall preview v4 first\. The detached waypoint stays visible on compatible Android 13\+ themed launchers\. <\/p>/,
  );
  assert.match(
    anchor,
    /trackEvent\(["']android_app_download["'],\s*\{\s*build:\s*["']preview_v5_debug_signed["'],\s*source:\s*["']account_settings["'],?\s*\}\)/,
  );
});

test("Android CI promotes the same-run build to an immutable preview release", () => {
  assert.match(
    WORKFLOW,
    /name:\s*gatepath-debug-apk[\s\S]*?path:\s*android\/app\/build\/outputs\/apk\/debug\/app-debug\.apk/,
    "the validation job must upload the compiled APK under the expected artifact name",
  );

  const publishJob = WORKFLOW.match(
    /\n  publish-preview:[\s\S]*?(?=\n  [a-zA-Z0-9_-]+:|$)/,
  )?.[0];
  assert.ok(publishJob, "missing publish-preview job");
  assert.match(publishJob, /needs:\s*validate-and-build/);
  assert.match(
    publishJob,
    /if:\s*github\.event_name == 'push' && github\.ref == 'refs\/heads\/main'/,
  );
  assert.match(publishJob, /permissions:\s*\n\s+contents:\s*write/);

  assert.match(publishJob, new RegExp(`gh release view ${RELEASE_TAG}\\b`));
  assert.match(publishJob, /uses:\s*actions\/download-artifact@v8/);
  assert.match(publishJob, /name:\s*gatepath-debug-apk/);
  assert.match(publishJob, /if:\s*steps\.preview\.outputs\.exists != 'true'/);
  assert.match(publishJob, new RegExp(`cp [^\\n]+ ${escapeRegExp(RELEASE_ASSET)}`));
  assert.match(
    publishJob,
    new RegExp(
      `sha256sum ${escapeRegExp(RELEASE_ASSET)} > ${escapeRegExp(RELEASE_CHECKSUM)}`,
    ),
  );
  const flattenedReleaseCommand = publishJob.replace(/\\\s+/g, " ");
  assert.match(
    flattenedReleaseCommand,
    new RegExp(
      `gh release create ${RELEASE_TAG}\\s+${escapeRegExp(RELEASE_ASSET)}\\s+${escapeRegExp(RELEASE_CHECKSUM)}`,
    ),
  );
  assert.match(publishJob, /--prerelease\b/);

  assert.doesNotMatch(publishJob, /gh release delete\b/);
  assert.doesNotMatch(publishJob, /gh release upload\b/);
  assert.doesNotMatch(publishJob, /--clobber\b/);
});
