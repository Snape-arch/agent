import { readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const assets = process.argv[2] ? resolve(process.argv[2]) : fileURLToPath(new URL('../../static/vision/assets/', import.meta.url));
const files = readdirSync(assets).filter((name) => name.endsWith('.js')).map((name) => ({ name, bytes: statSync(join(assets, name)).size }));
const initial = files.find((file) => /^index-/.test(file.name));
const threeCore = files.find((file) => /^three-core-/.test(file.name));
const failures = [];
if (!initial || initial.bytes > 190_000) failures.push(`initial application chunk exceeds 190 KB: ${initial?.bytes ?? 'missing'}`);
if (!threeCore || threeCore.bytes > 560_000) failures.push(`lazy Three.js core exceeds 560 KB: ${threeCore?.bytes ?? 'missing'}`);
for (const file of files.filter((item) => /^three-(controls|loaders|geometries)-/.test(item.name))) {
  if (file.bytes > 120_000) failures.push(`${file.name} exceeds 120 KB`);
}
for (const file of files.filter((item) => /^three-animation-/.test(item.name))) {
  if (file.bytes > 80_000) failures.push(`${file.name} exceeds 80 KB`);
}
console.log(JSON.stringify({ ok: !failures.length, initial, threeCore, chunks: files, failures }));
if (failures.length) process.exit(1);
