// Download Merida SVG chess pieces from lichess and store under public/pieces/merida
// Usage: npm --prefix apps/renderer run fetch-pieces

import fs from 'node:fs';
import path from 'node:path';

// Expect to be run with cwd=apps/renderer
const ROOT = process.cwd();
const OUT_DIR_PUBLIC = path.join(ROOT, 'public', 'pieces', 'merida');
const OUT_DIR_SRC = path.join(ROOT, 'src', 'assets', 'pieces', 'merida');

const map = {
  wk: 'wK', wq: 'wQ', wr: 'wR', wb: 'wB', wn: 'wN', wp: 'wP',
  bk: 'bK', bq: 'bQ', br: 'bR', bb: 'bB', bn: 'bN', bp: 'bP',
};

async function ensureDir(dir) {
  await fs.promises.mkdir(dir, {recursive: true});
}

async function download(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  return await res.text();
}

async function run() {
  await ensureDir(OUT_DIR_PUBLIC);
  await ensureDir(OUT_DIR_SRC);
  const base = 'https://raw.githubusercontent.com/lichess-org/lila/master/public/piece/merida';
  let ok = 0;
  for (const [local, remote] of Object.entries(map)) {
    const url = `${base}/${remote}.svg`;
    const destPublic = path.join(OUT_DIR_PUBLIC, `${local}.svg`);
    const destSrc = path.join(OUT_DIR_SRC, `${local}.svg`);
    try {
      const svg = await download(url);
      await fs.promises.writeFile(destPublic, svg, 'utf8');
      await fs.promises.writeFile(destSrc, svg, 'utf8');
      ok++;
      console.log('Saved', path.relative(ROOT, destPublic));
    } catch (e) {
      console.error('Failed', url, e.message);
    }
  }
  console.log(`Downloaded ${ok}/12 Merida pieces to`, path.relative(ROOT, OUT_DIR_PUBLIC), 'and', path.relative(ROOT, OUT_DIR_SRC));
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});


