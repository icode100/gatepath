import assert from "node:assert/strict";
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ANDROID = resolve(ROOT, "android");
const PACKAGE_ID = "com.icode100.gatepath";
const HOST = "gatepath.vercel.app";
const DEFAULT_URL = `https://${HOST}/`;
const ASSETLINKS_PLACEHOLDER =
  "REPLACE_WITH_THE_APP_SIGNING_CERTIFICATE_SHA256_FINGERPRINT";
const GRADLE_8111_BIN_SHA256 =
  "f397b287023acdba1e9f6fc5ea72d22dd63669d59ed4a289a29b1a76eee151c6";

function read(...segments) {
  return readFileSync(resolve(ROOT, ...segments), "utf8");
}

function androidResource(...segments) {
  return read("android", "app", "src", "main", "res", ...segments);
}

function resourceString(source, name) {
  const match = source.match(
    new RegExp(`<string\\b[^>]*\\bname=["']${name}["'][^>]*>([\\s\\S]*?)<\\/string>`),
  );
  assert.ok(match, `missing Android string resource ${name}`);
  return match[1].trim();
}

function parseProperties(source) {
  return Object.fromEntries(
    source
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#"))
      .map((line) => {
        const separator = line.indexOf("=");
        assert.notEqual(separator, -1, `invalid properties entry: ${line}`);
        return [line.slice(0, separator), line.slice(separator + 1)];
      }),
  );
}

function assertAdaptiveIcon(source, { monochrome, label }) {
  assert.match(source, /<adaptive-icon\b/, `${label} must be an adaptive icon`);
  assert.match(
    source,
    /<background\b[^>]*android:drawable=["']@drawable\/ic_launcher_background["']/,
    `${label} must use the dedicated background layer`,
  );
  assert.match(
    source,
    /<foreground\b[^>]*android:drawable=["']@drawable\/ic_launcher_foreground["']/,
    `${label} must use the dedicated foreground layer`,
  );
  if (monochrome) {
    assert.match(
      source,
      /<monochrome\b[^>]*android:drawable=["']@drawable\/ic_launcher_monochrome["']/,
      `${label} must expose the Android 13 themed-icon layer`,
    );
  } else {
    assert.doesNotMatch(
      source,
      /<monochrome\b/,
      `${label} must leave the API 33-only monochrome tag to the v33 override`,
    );
  }
}

function colorChannels(value) {
  assert.match(value, /^#[0-9a-f]{6}(?:[0-9a-f]{2})?$/i, `unsupported vector color ${value}`);
  const hex = value.slice(1).toUpperCase();
  if (hex.length === 6) return { alpha: "FF", rgb: hex };
  return { alpha: hex.slice(0, 2), rgb: hex.slice(2) };
}

test("Android wrapper pins the GatePath application ID and production origin", () => {
  const appGradle = read("android", "app", "build.gradle");
  const manifest = read("android", "app", "src", "main", "AndroidManifest.xml");
  const strings = androidResource("values", "strings.xml");

  assert.match(appGradle, new RegExp(`\\bnamespace\\s+["']${PACKAGE_ID.replaceAll(".", "\\.")}["']`));
  assert.match(appGradle, new RegExp(`\\bapplicationId\\s+["']${PACKAGE_ID.replaceAll(".", "\\.")}["']`));
  assert.match(appGradle, /\bcompileSdk\s+36\b/);
  assert.match(appGradle, /\btargetSdk\s+36\b/);
  assert.match(read("android", "build.gradle"), /version\s+["']8\.10\.1["']/);
  assert.equal(resourceString(strings, "default_url"), DEFAULT_URL);
  assert.equal(
    resourceString(strings, "web_manifest_url"),
    `${DEFAULT_URL}manifest.webmanifest`,
  );
  assert.equal(resourceString(strings, "provider_authority"), `${PACKAGE_ID}.fileprovider`);

  const assetStatements = JSON.parse(resourceString(strings, "asset_statements"));
  assert.deepEqual(assetStatements, [
    {
      relation: ["delegate_permission/common.handle_all_urls"],
      target: { namespace: "web", site: DEFAULT_URL.slice(0, -1) },
    },
  ]);

  assert.match(
    manifest,
    /android:name=["']android\.support\.customtabs\.trusted\.DEFAULT_URL["'][\s\S]*?android:value=["']@string\/default_url["']/,
  );
  assert.match(manifest, /<intent-filter\b[^>]*android:autoVerify=["']true["']/);
  assert.match(manifest, new RegExp(`android:host=["']${HOST.replaceAll(".", "\\.")}["']`));
  assert.match(manifest, /android:scheme=["']https["']/);
  assert.match(manifest, /android:pathPrefix=["']\/["']/);
  assert.match(manifest, /android:usesCleartextTraffic=["']false["']/);
});

test("Android manifest references the normal and round adaptive launcher icons", () => {
  const manifest = read("android", "app", "src", "main", "AndroidManifest.xml");
  const applicationTag = manifest.match(/<application\b[\s\S]*?>/)?.[0];
  assert.ok(applicationTag, "AndroidManifest.xml must contain an application element");
  assert.match(applicationTag, /android:icon=["']@mipmap\/ic_launcher["']/);
  assert.match(applicationTag, /android:roundIcon=["']@mipmap\/ic_launcher_round["']/);
});

test("Android Browser Helper launch components are declared safely", () => {
  const manifest = read("android", "app", "src", "main", "AndroidManifest.xml");
  const applicationTag = manifest.match(/<application\b[\s\S]*?>/)?.[0];
  assert.ok(applicationTag, "AndroidManifest.xml must contain an application element");
  assert.match(
    manifest,
    /<uses-permission\b[^>]*android:name=["']android\.permission\.REORDER_TASKS["'][^>]*\/>/,
  );
  assert.match(
    applicationTag,
    /android:manageSpaceActivity=["']com\.google\.androidbrowserhelper\.trusted\.ManageDataLauncherActivity["']/,
  );

  const launcher = manifest.match(
    /<activity\b[^>]*android:name=["']com\.google\.androidbrowserhelper\.trusted\.LauncherActivity["'][\s\S]*?<\/activity>/,
  )?.[0];
  assert.ok(launcher, "missing Android Browser Helper launcher activity");
  assert.match(
    launcher.match(/<activity\b[^>]*>/)?.[0] ?? "",
    /android:alwaysRetainTaskState=["']true["']/,
  );
  assert.doesNotMatch(
    launcher.match(/<activity\b[^>]*>/)?.[0] ?? "",
    /android:launchMode=["']singleTask["']/,
    "LauncherActivity explicitly warns that singleTask clobbers the browser activity",
  );

  const focus = manifest.match(
    /<activity\b[^>]*android:name=["']com\.google\.androidbrowserhelper\.trusted\.FocusActivity["'][^>]*\/>/,
  )?.[0];
  assert.ok(focus, "missing Android Browser Helper focus activity");
  assert.match(focus, /android:exported=["']true["']/);

  const manageData = manifest.match(
    /<activity\b[^>]*android:name=["']com\.google\.androidbrowserhelper\.trusted\.ManageDataLauncherActivity["'][\s\S]*?<\/activity>/,
  )?.[0];
  assert.ok(
    manageData,
    "LauncherActivity configures ManageDataLauncherActivity during every modern Android launch",
  );
  assert.match(manageData.match(/<activity\b[^>]*>/)?.[0] ?? "", /android:enabled=["']true["']/);
  assert.match(manageData, /android:name=["']android\.intent\.action\.APPLICATION_PREFERENCES["']/);
  assert.match(manageData, /android:name=["']android\.intent\.category\.DEFAULT["']/);
  assert.match(
    manageData,
    /android:name=["']android\.support\.customtabs\.trusted\.MANAGE_SPACE_URL["'][\s\S]*?android:value=["']@string\/default_url["']/,
  );
});

test("API 27 navigation-bar attributes stay out of the API 23 base theme", () => {
  const baseTheme = androidResource("values", "styles.xml");
  const api27Theme = androidResource("values-v27", "styles.xml");

  assert.doesNotMatch(baseTheme, /android:windowLightNavigationBar/);
  assert.match(api27Theme, /android:windowLightNavigationBar/);
});

test("normal and round launchers use adaptive v26 layers and v33 monochrome overrides", () => {
  for (const iconName of ["ic_launcher.xml", "ic_launcher_round.xml"]) {
    assertAdaptiveIcon(androidResource("mipmap-anydpi-v26", iconName), {
      monochrome: false,
      label: `mipmap-anydpi-v26/${iconName}`,
    });
    assertAdaptiveIcon(androidResource("mipmap-anydpi-v33", iconName), {
      monochrome: true,
      label: `mipmap-anydpi-v33/${iconName}`,
    });
  }
});

test("monochrome launcher drawable is a one-color, background-free vector", () => {
  const source = androidResource("drawable", "ic_launcher_monochrome.xml");
  assert.match(source, /<vector\b/);
  assert.match(source, /android:width=["']108dp["']/);
  assert.match(source, /android:height=["']108dp["']/);
  assert.match(source, /android:viewportWidth=["']108["']/);
  assert.match(source, /android:viewportHeight=["']108["']/);
  assert.doesNotMatch(source, /<(?:background|bitmap|gradient|shape|solid)\b/i);
  assert.doesNotMatch(source, /android:tint=/i);

  const paths = [...source.matchAll(/<path\b[\s\S]*?\/>/g)].map((match) => match[0]);
  assert.equal(
    paths.length,
    3,
    "the Route-G monochrome mark must contain separate arc, crossbar and waypoint paths",
  );
  for (const path of paths) {
    assert.match(path, /android:pathData=["'][^"']+["']/);
  }
  assert.doesNotMatch(
    paths.map((path) => path.match(/android:pathData=["']([^"']+)["']/)?.[1] ?? "").join(" "),
    /M\s*0(?:\.0+)?[, ]\s*0(?:\.0+)?[^M]*(?:108)[^M]*(?:108)/i,
    "monochrome drawable must not contain an obvious full-canvas background path",
  );

  const colorValues = [...source.matchAll(/android:(?:fillColor|strokeColor)=["']([^"']+)["']/g)]
    .map((match) => match[1]);
  assert.ok(colorValues.length > 0, "monochrome vector must declare its path colors directly");
  const visibleColors = colorValues
    .map(colorChannels)
    .filter(({ alpha }) => alpha !== "00");
  assert.ok(visibleColors.length > 0, "monochrome vector must contain visible artwork");
  assert.ok(
    visibleColors.every(({ alpha }) => alpha === "FF"),
    "visible monochrome paths must be fully opaque so the launcher owns the tint",
  );
  assert.equal(
    new Set(visibleColors.map(({ rgb }) => rgb)).size,
    1,
    "visible monochrome paths must use exactly one RGB color",
  );

  const strokedPaths = paths.filter((path) => /android:strokeColor=/.test(path));
  const arcPath = strokedPaths.find((path) => /android:pathData=["'][^"']*[aA][\d.]+,[\d.]+/.test(path));
  const barPath = strokedPaths.find((path) => /android:pathData=["'][^"']*H[\d.]+/.test(path));
  const waypointPath = paths.find(
    (path) => /android:fillColor=["']#FF000000["']/.test(path) && !/android:strokeColor=/.test(path),
  );
  assert.equal(strokedPaths.length, 2, "only the arc and crossbar should use strokes");
  assert.ok(arcPath, "monochrome vector must contain the stroked Route-G arc");
  assert.ok(barPath, "monochrome vector must contain an independent horizontal crossbar");
  assert.ok(waypointPath, "monochrome vector must contain a dedicated waypoint path");
  assert.doesNotMatch(
    source,
    /<clip-path\b/,
    "the waypoint must be genuinely detached instead of simulated with a cut-out halo",
  );

  const arcGeometry = arcPath.match(
    /android:pathData=["']M([\d.]+),([\d.]+)A([\d.]+),([\d.]+)\s+0,1\s+0,([\d.]+),?([\d.]+)["']/,
  );
  const barGeometry = barPath.match(
    /android:pathData=["']M([\d.]+),([\d.]+)H([\d.]+)["']/,
  );
  const arcStrokeWidth = Number(arcPath.match(/android:strokeWidth=["']([\d.]+)["']/)?.[1]);
  const barStrokeWidth = Number(barPath.match(/android:strokeWidth=["']([\d.]+)["']/)?.[1]);
  const waypointGeometry = waypointPath.match(
    /android:pathData=["']M([\d.]+),([\d.]+)a([\d.]+),\3\s+0,1\s+1,-([\d.]+)\s+0/,
  );
  assert.ok(arcGeometry, "Route-G must retain its canonical counter-clockwise circular arc");
  assert.ok(barGeometry, "Route-G crossbar must remain a straight horizontal segment");
  assert.ok(Number.isFinite(arcStrokeWidth), "Route-G arc must declare a numeric stroke width");
  assert.ok(Number.isFinite(barStrokeWidth), "Route-G crossbar must declare a numeric stroke width");
  assert.ok(waypointGeometry, "waypoint must remain a circular vector path");

  const arcValues = arcGeometry.slice(1).map(Number);
  const expectedArcValues = [65.34, 42.14, 18.56, 18.56, 65.34, 68.86];
  for (let index = 0; index < expectedArcValues.length; index += 1) {
    assert.ok(
      Math.abs(arcValues[index] - expectedArcValues[index]) <= 0.1,
      "the monochrome arc must retain the measured reference geometry",
    );
  }
  assert.ok(Math.abs(arcStrokeWidth - 7.22) <= 0.1, "the arc stroke must match the Route-G weight");

  const [barStartX, barCenterY, barEndX] = barGeometry.slice(1).map(Number);
  assert.ok(
    Math.abs(barStartX - 55.03) <= 0.1 &&
      Math.abs(barCenterY - 56.06) <= 0.1 &&
      Math.abs(barEndX - 60.5) <= 0.1 &&
      Math.abs(barStrokeWidth - 7.22) <= 0.1,
    "the independent crossbar must retain the measured pill geometry",
  );

  const waypointRadius = Number(waypointGeometry[3]);
  const waypointCenterX = Number(waypointGeometry[1]) - waypointRadius;
  const waypointCenterY = Number(waypointGeometry[2]);
  assert.ok(
    Math.abs(waypointCenterX - 71.01) <= 0.1 &&
      Math.abs(waypointCenterY - 56.06) <= 0.1 &&
      Math.abs(waypointRadius - 4.64) <= 0.1,
    "the circular waypoint must retain the full-color launcher's size and position",
  );
  assert.ok(
    Math.abs(waypointCenterY - barCenterY) <= 0.1,
    "the crossbar and waypoint must share the reference mark's horizontal axis",
  );

  const leftGap = waypointCenterX - waypointRadius - (barEndX + barStrokeWidth / 2);
  assert.ok(
    leftGap >= 1 && leftGap <= 5,
    "the waypoint needs a visible but cohesive transparent gap to its left",
  );

  const lowerEndpointX = arcValues[4];
  const lowerEndpointY = arcValues[5];
  const lowerGap = Math.hypot(
    waypointCenterX - lowerEndpointX,
    waypointCenterY - lowerEndpointY,
  ) - waypointRadius - arcStrokeWidth / 2;
  assert.ok(
    lowerGap >= 2 && lowerGap <= 10,
    "the waypoint needs a visible transparent lower-side gap from the Route-G arc",
  );

  const halfChord = (arcValues[5] - arcValues[1]) / 2;
  const arcCenterX = arcValues[0] - Math.sqrt(arcValues[2] ** 2 - halfChord ** 2);
  const arcCenterY = (arcValues[1] + arcValues[5]) / 2;
  assert.ok(
    Math.hypot(arcCenterX - 54, arcCenterY - 54) + arcValues[2] + arcStrokeWidth / 2 <= 33 &&
      Math.max(
        Math.hypot(barStartX - 54, barCenterY - 54),
        Math.hypot(barEndX - 54, barCenterY - 54),
      ) + barStrokeWidth / 2 <= 33 &&
    Math.hypot(waypointCenterX - 54, waypointCenterY - 54) + waypointRadius <= 33,
    "all three monochrome pieces must remain inside Android's 66dp adaptive-icon safe circle",
  );

  const foreground = read("android", "app", "src", "main", "res", "drawable", "ic_launcher_foreground.xml");
  const coloredWaypointData = foreground.match(
    /android:fillColor=["']@color\/launcher_waypoint["']\s+android:pathData=["']([^"']+)["']/,
  )?.[1];
  const monochromeWaypointData = waypointPath.match(/android:pathData=["']([^"']+)["']/)?.[1];
  assert.ok(coloredWaypointData, "full-color launcher must retain its waypoint geometry");
  assert.equal(
    coloredWaypointData,
    "M75.65,56.06a4.64,4.64 0,1 1,-9.28 0a4.64,4.64 0,1 1,9.28 0z",
    "the full-color launcher waypoint must not change with the monochrome redesign",
  );
  assert.equal(
    monochromeWaypointData,
    coloredWaypointData,
    "the monochrome waypoint must align exactly with the full-color launcher waypoint",
  );
});

test("Digital Asset Links template is pinned to GatePath and cannot masquerade as production", () => {
  const statements = JSON.parse(read("android", "assetlinks.example.json"));
  assert.equal(statements.length, 1);
  const [statement] = statements;
  assert.deepEqual(statement.relation, ["delegate_permission/common.handle_all_urls"]);
  assert.equal(statement.target.namespace, "android_app");
  assert.equal(statement.target.package_name, PACKAGE_ID);
  assert.deepEqual(statement.target.sha256_cert_fingerprints, [ASSETLINKS_PLACEHOLDER]);
  assert.doesNotMatch(
    ASSETLINKS_PLACEHOLDER,
    /^(?:[0-9A-F]{2}:){31}[0-9A-F]{2}$/,
    "the example must remain an unmistakable placeholder until a real signing key exists",
  );
});

test("Gradle wrapper is complete and pins a checksum-verified distribution", () => {
  const propertiesPath = resolve(ANDROID, "gradle", "wrapper", "gradle-wrapper.properties");
  const wrapperJar = resolve(ANDROID, "gradle", "wrapper", "gradle-wrapper.jar");
  const properties = parseProperties(readFileSync(propertiesPath, "utf8"));

  assert.equal(
    properties.distributionUrl,
    "https\\://services.gradle.org/distributions/gradle-8.11.1-bin.zip",
  );
  assert.equal(properties.distributionSha256Sum, GRADLE_8111_BIN_SHA256);
  assert.equal(properties.validateDistributionUrl, "true");
  assert.ok(Number(properties.networkTimeout) >= 10_000, "wrapper network timeout is unexpectedly short");
  assert.ok(existsSync(wrapperJar), "missing Gradle wrapper JAR");
  assert.ok(statSync(wrapperJar).size > 40_000, "Gradle wrapper JAR is unexpectedly small");
  assert.ok(existsSync(resolve(ANDROID, "gradlew")), "missing Unix Gradle wrapper script");
  assert.ok(existsSync(resolve(ANDROID, "gradlew.bat")), "missing Windows Gradle wrapper script");

  const gradleProperties = parseProperties(read("android", "gradle.properties"));
  assert.equal(gradleProperties["android.useAndroidX"], "true");
  assert.equal(gradleProperties["android.nonTransitiveRClass"], "true");
  assert.match(gradleProperties["org.gradle.jvmargs"] ?? "", /-Dfile\.encoding=UTF-8/);
});

test("repository ignores Android signing secrets, local SDK state and build outputs", () => {
  const ignoreLines = new Set(
    read(".gitignore")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#")),
  );

  for (const required of [
    "*.jks",
    "*.keystore",
    "key.properties",
    "/android/local.properties",
    "/android/.gradle/",
    "/android/**/build/",
    "*.apk",
    "*.aab",
  ]) {
    assert.ok(ignoreLines.has(required), `.gitignore must contain ${required}`);
  }
});
