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
