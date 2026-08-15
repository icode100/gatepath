import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { inflateSync } from "node:zlib";

import { loadTypeScriptModule } from "./load-typescript-module.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const manifest = loadTypeScriptModule("app/manifest.ts").default();
const PNG_SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

function paeth(left, above, upperLeft) {
  const estimate = left + above - upperLeft;
  const leftDistance = Math.abs(estimate - left);
  const aboveDistance = Math.abs(estimate - above);
  const upperLeftDistance = Math.abs(estimate - upperLeft);
  if (leftDistance <= aboveDistance && leftDistance <= upperLeftDistance) return left;
  return aboveDistance <= upperLeftDistance ? above : upperLeft;
}

function decodeRgbaPng(path) {
  const source = readFileSync(path);
  assert.ok(source.subarray(0, 8).equals(PNG_SIGNATURE), `${path} must have a PNG signature`);

  let offset = 8;
  let header;
  let reachedEnd = false;
  const compressedParts = [];
  while (offset < source.length) {
    assert.ok(offset + 12 <= source.length, `${path} has a truncated PNG chunk`);
    const length = source.readUInt32BE(offset);
    const type = source.toString("ascii", offset + 4, offset + 8);
    const dataStart = offset + 8;
    const dataEnd = dataStart + length;
    assert.ok(dataEnd + 4 <= source.length, `${path} has a truncated ${type} chunk`);
    const data = source.subarray(dataStart, dataEnd);
    if (type === "IHDR") {
      assert.equal(length, 13, `${path} has an invalid IHDR length`);
      header = {
        width: data.readUInt32BE(0),
        height: data.readUInt32BE(4),
        bitDepth: data[8],
        colorType: data[9],
        compression: data[10],
        filter: data[11],
        interlace: data[12],
      };
    } else if (type === "IDAT") {
      compressedParts.push(data);
    } else if (type === "IEND") {
      reachedEnd = true;
      break;
    }
    offset = dataEnd + 4;
  }

  assert.ok(header, `${path} must contain IHDR`);
  assert.ok(reachedEnd, `${path} must contain IEND`);
  assert.ok(compressedParts.length > 0, `${path} must contain image data`);
  assert.equal(header.bitDepth, 8, `${path} must use 8-bit channels`);
  assert.equal(header.colorType, 6, `${path} must be RGBA`);
  assert.equal(header.compression, 0, `${path} uses an unsupported compression method`);
  assert.equal(header.filter, 0, `${path} uses an unsupported filter method`);
  assert.equal(header.interlace, 0, `${path} must not be interlaced`);

  const bytesPerPixel = 4;
  const stride = header.width * bytesPerPixel;
  const encoded = inflateSync(Buffer.concat(compressedParts));
  assert.equal(
    encoded.length,
    header.height * (stride + 1),
    `${path} has an unexpected decompressed size`,
  );

  const pixels = Buffer.alloc(header.height * stride);
  for (let y = 0; y < header.height; y += 1) {
    const encodedRow = y * (stride + 1);
    const filterType = encoded[encodedRow];
    assert.ok(filterType <= 4, `${path} uses unsupported PNG filter ${filterType}`);
    const outputRow = y * stride;
    for (let x = 0; x < stride; x += 1) {
      const raw = encoded[encodedRow + 1 + x];
      const left = x >= bytesPerPixel ? pixels[outputRow + x - bytesPerPixel] : 0;
      const above = y > 0 ? pixels[outputRow - stride + x] : 0;
      const upperLeft = y > 0 && x >= bytesPerPixel
        ? pixels[outputRow - stride + x - bytesPerPixel]
        : 0;
      let value;
      if (filterType === 0) value = raw;
      else if (filterType === 1) value = raw + left;
      else if (filterType === 2) value = raw + above;
      else if (filterType === 3) value = raw + Math.floor((left + above) / 2);
      else value = raw + paeth(left, above, upperLeft);
      pixels[outputRow + x] = value & 0xff;
    }
  }

  return { ...header, pixels };
}

function localPath(src) {
  assert.ok(src.startsWith("/"), `manifest icon ${src} must be root-relative`);
  const publicPath = resolve(ROOT, "public", src.slice(1));
  if (existsSync(publicPath)) return publicPath;
  // Next App Router metadata files such as app/icon.svg are exposed at the
  // site root without also living under public/.
  return resolve(ROOT, "app", src.slice(1));
}

function declaredDimensions(sizes) {
  const match = /^(\d+)x(\d+)$/.exec(sizes ?? "");
  assert.ok(match, `expected fixed PNG dimensions, received ${sizes}`);
  return { width: Number(match[1]), height: Number(match[2]) };
}

function visiblePixels(image, isVisible) {
  const visible = [];
  for (let index = 0; index < image.pixels.length; index += 4) {
    const rgba = image.pixels.subarray(index, index + 4);
    if (!isVisible(rgba)) continue;
    const pixelIndex = index / 4;
    visible.push({
      x: pixelIndex % image.width,
      y: Math.floor(pixelIndex / image.width),
      rgba,
    });
  }
  return visible;
}

function colorDistance(pixel, expected) {
  return Math.max(
    Math.abs(pixel[0] - expected[0]),
    Math.abs(pixel[1] - expected[1]),
    Math.abs(pixel[2] - expected[2]),
  );
}

function pixelAt(image, normalizedX, normalizedY) {
  const x = Math.min(image.width - 1, Math.max(0, Math.round(normalizedX * (image.width - 1))));
  const y = Math.min(image.height - 1, Math.max(0, Math.round(normalizedY * (image.height - 1))));
  const offset = (y * image.width + x) * 4;
  return image.pixels.subarray(offset, offset + 4);
}

function alphaComponents(image, minimumAlpha = 64) {
  const pixelCount = image.width * image.height;
  const visited = new Uint8Array(pixelCount);
  const queue = new Int32Array(pixelCount);
  const components = [];

  for (let seed = 0; seed < pixelCount; seed += 1) {
    if (visited[seed] || image.pixels[seed * 4 + 3] < minimumAlpha) continue;
    visited[seed] = 1;
    let head = 0;
    let tail = 1;
    queue[0] = seed;
    let size = 0;
    let minX = image.width;
    let maxX = -1;
    let minY = image.height;
    let maxY = -1;

    while (head < tail) {
      const index = queue[head];
      head += 1;
      size += 1;
      const x = index % image.width;
      const y = Math.floor(index / image.width);
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);

      for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
        for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
          if (offsetX === 0 && offsetY === 0) continue;
          const neighborX = x + offsetX;
          const neighborY = y + offsetY;
          if (
            neighborX < 0 || neighborX >= image.width ||
            neighborY < 0 || neighborY >= image.height
          ) continue;
          const neighbor = neighborY * image.width + neighborX;
          if (visited[neighbor] || image.pixels[neighbor * 4 + 3] < minimumAlpha) continue;
          visited[neighbor] = 1;
          queue[tail] = neighbor;
          tail += 1;
        }
      }
    }

    components.push({ size, minX, maxX, minY, maxY });
  }

  return components;
}

function importedComponentSource(entrySource, componentName) {
  const importPattern = new RegExp(
    `import\\s+(?:\\{[^}]*\\b${componentName}\\b[^}]*\\}|${componentName})\\s+from\\s+["']([^"']+)["']`,
  );
  const match = entrySource.match(importPattern);
  assert.ok(match, `${componentName} must be imported by AuthDialog`);
  const specifier = match[1];
  const base = specifier.startsWith("@/")
    ? resolve(ROOT, specifier.slice(2))
    : resolve(ROOT, "components", "auth", specifier);
  for (const suffix of ["", ".tsx", ".ts"]) {
    const path = `${base}${suffix}`;
    if (existsSync(path)) return readFileSync(path, "utf8");
  }
  assert.fail(`could not resolve ${componentName} from ${specifier}`);
}

function maximumNormalizedRadius(pixels, width, height) {
  return Math.max(
    ...pixels.map(({ x, y }) =>
      Math.hypot((x + 0.5) / width - 0.5, (y + 0.5) / height - 0.5)),
  );
}

test("manifest advertises dedicated any, maskable and monochrome launcher icons", () => {
  const icons = manifest.icons ?? [];
  const findIcon = (purpose, sizes) =>
    icons.find((icon) => icon.purpose === purpose && icon.sizes === sizes);

  assert.ok(findIcon("any", "192x192"), "missing 192px standard icon");
  assert.ok(findIcon("any", "512x512"), "missing 512px standard icon");
  const maskable = findIcon("maskable", "512x512");
  const monochrome = findIcon("monochrome", "512x512");
  assert.ok(maskable, "missing 512px maskable icon");
  assert.ok(monochrome, "missing 512px monochrome icon");
  assert.equal(monochrome.type, "image/png");
  assert.notEqual(monochrome.src, maskable.src, "monochrome and maskable icons must be distinct assets");
});

test("every local manifest icon exists and matches its declared type and dimensions", () => {
  for (const icon of manifest.icons ?? []) {
    const path = localPath(icon.src);
    assert.ok(existsSync(path), `missing manifest icon ${icon.src}`);
    if (icon.type === "image/svg+xml") {
      const source = readFileSync(path, "utf8");
      assert.match(source, /<svg\b/i);
      assert.match(source, /\bviewBox\s*=\s*["'][^"']+["']/i);
      assert.equal(icon.sizes, "any");
      continue;
    }

    assert.equal(icon.type, "image/png", `${icon.src} must declare its PNG type`);
    const expected = declaredDimensions(icon.sizes);
    const image = decodeRgbaPng(path);
    assert.equal(image.width, expected.width, `${icon.src} width does not match its manifest entry`);
    assert.equal(image.height, expected.height, `${icon.src} height does not match its manifest entry`);
  }
});

test("maskable artwork remains inside the guaranteed central safe circle", () => {
  const icon = manifest.icons.find((candidate) => candidate.purpose === "maskable");
  assert.ok(icon);
  const image = decodeRgbaPng(localPath(icon.src));
  const background = image.pixels.subarray(0, 4);
  const visible = visiblePixels(image, ([red, green, blue, alpha]) =>
    alpha > 8 && Math.max(
      Math.abs(red - background[0]),
      Math.abs(green - background[1]),
      Math.abs(blue - background[2]),
    ) > 8,
  );

  assert.ok(visible.length > image.width * image.height * 0.05, "maskable glyph is unexpectedly small");
  assert.ok(
    maximumNormalizedRadius(visible, image.width, image.height) <= 0.4,
    "maskable glyph extends beyond the centered 80% safe circle",
  );
});

test("colored launcher artwork retains the orange GatePath waypoint", () => {
  const coloredIcons = (manifest.icons ?? []).filter(
    (icon) => icon.type === "image/png" && icon.purpose !== "monochrome",
  );
  assert.ok(coloredIcons.length >= 3, "expected standard and maskable colored launchers");

  const waypoint = [0xd9, 0x6a, 0x42];
  for (const icon of coloredIcons) {
    const image = decodeRgbaPng(localPath(icon.src));
    const brandedPixels = visiblePixels(image, (rgba) =>
      rgba[3] > 200 && colorDistance(rgba, waypoint) <= 12,
    );
    assert.ok(
      brandedPixels.length > image.width * image.height * 0.002,
      `${icon.src} lost the orange GatePath waypoint`,
    );
    assert.ok(
      brandedPixels.some(({ x, y }) => x / image.width > 0.68 && y / image.height > 0.45),
      `${icon.src} waypoint is no longer at the Route-G terminal`,
    );
  }
});

test("monochrome icon is a single-color alpha glyph inside the safe circle", () => {
  const icon = manifest.icons.find((candidate) => candidate.purpose === "monochrome");
  assert.ok(icon);
  const image = decodeRgbaPng(localPath(icon.src));
  assert.equal(image.pixels[3], 0, "monochrome icon background must be transparent");
  const visible = visiblePixels(image, ([, , , alpha]) => alpha > 8);
  assert.ok(visible.length > image.width * image.height * 0.05, "monochrome glyph is unexpectedly small");
  assert.ok(
    maximumNormalizedRadius(visible, image.width, image.height) <= 0.4,
    "monochrome glyph extends beyond the centered 80% safe circle",
  );
  const colors = new Set(visible.map(({ rgba }) => `${rgba[0]},${rgba[1]},${rgba[2]}`));
  assert.equal(colors.size, 1, "monochrome glyph must contain exactly one RGB color");
});

test("monochrome Route-G aligns its waypoint and preserves a visible themeable outline", () => {
  const icon = manifest.icons.find((candidate) => candidate.purpose === "monochrome");
  const maskableIcon = manifest.icons.find((candidate) => candidate.purpose === "maskable");
  assert.ok(icon);
  assert.ok(maskableIcon);
  const image = decodeRgbaPng(localPath(icon.src));
  const maskable = decodeRgbaPng(localPath(maskableIcon.src));

  const meaningful = alphaComponents(image)
    .filter(({ size }) => size > image.width * image.height * 0.001)
    .sort((left, right) => right.size - left.size);
  assert.ok(
    meaningful.length >= 2,
    "the themed mark must keep its waypoint separate from the Route-G alpha",
  );
  const waypoint = meaningful.reduce((rightmost, component) =>
    component.minX > rightmost.minX ? component : rightmost,
  );
  const routeComponents = meaningful.filter((component) => component !== waypoint);
  const routeSize = routeComponents.reduce((total, component) => total + component.size, 0);
  assert.ok(routeSize > waypoint.size * 4, "the route must remain the dominant artwork");
  const waypointWidth = waypoint.maxX - waypoint.minX + 1;
  const waypointHeight = waypoint.maxY - waypoint.minY + 1;
  assert.ok(
    Math.abs(waypointWidth - waypointHeight) <= image.width * 0.015,
    "the outlined waypoint must remain recognizably circular",
  );

  const orangePixels = visiblePixels(maskable, (rgba) =>
    rgba[3] > 200 && colorDistance(rgba, [0xd9, 0x6a, 0x42]) <= 12,
  );
  assert.ok(orangePixels.length > 0, "maskable icon is missing its canonical orange waypoint");
  const coloredCenterX = (Math.min(...orangePixels.map(({ x }) => x)) + Math.max(...orangePixels.map(({ x }) => x))) / 2;
  const coloredCenterY = (Math.min(...orangePixels.map(({ y }) => y)) + Math.max(...orangePixels.map(({ y }) => y))) / 2;
  const monoCenterX = (waypoint.minX + waypoint.maxX) / 2;
  const monoCenterY = (waypoint.minY + waypoint.maxY) / 2;
  assert.ok(
    Math.abs(monoCenterX / image.width - coloredCenterX / maskable.width) <= 0.01 &&
      Math.abs(monoCenterY / image.height - coloredCenterY / maskable.height) <= 0.01,
    "monochrome waypoint must stay aligned with the full-color maskable icon",
  );

  assert.ok(pixelAt(image, 0.76, 0.54)[3] >= 220, "waypoint center must remain opaque");
  assert.ok(pixelAt(image, 0.68, 0.54)[3] >= 220, "route terminal must remain opaque");
  assert.ok(
    pixelAt(image, 0.7075, 0.54)[3] <= 32,
    "a thin transparent outline must prevent the route from bleeding through the waypoint",
  );
});

test("Google sign-in uses the accessible official four-color G instead of a text initial", () => {
  const authDialog = readFileSync(resolve(ROOT, "components", "auth", "AuthDialog.tsx"), "utf8");
  const button = authDialog.match(
    /<button\b[^>]*className=["']auth-google["'][\s\S]*?<\/button>/,
  )?.[0];
  assert.ok(button, "missing Google sign-in button");
  assert.doesNotMatch(button, />\s*G\s*</, "Google sign-in must not use a plain text G");

  const componentName = button.match(/<(Google[A-Za-z0-9_]*)\b/)?.[1];
  const logoSource = /<svg\b/.test(button)
    ? button
    : componentName
      ? importedComponentSource(authDialog, componentName)
      : "";
  assert.ok(logoSource, "Google sign-in must render an SVG Google G");
  assert.match(logoSource, /<svg\b/);
  assert.match(logoSource, /aria-hidden=["']true["']/, "button text should name the decorative Google G");
  assert.ok(
    [...logoSource.matchAll(/<path\b/g)].length >= 4,
    "official Google G artwork must retain its four vector segments",
  );
  for (const color of ["4285f4", "34a853", "fbbc05", "ea4335"]) {
    assert.match(
      logoSource.toLowerCase(),
      new RegExp(`#${color}\\b`),
      `official Google G is missing #${color.toUpperCase()}`,
    );
  }
});
