import { mkdir, readFile, writeFile } from 'node:fs/promises';

await mkdir('dist/server', { recursive: true });
const [page, worker] = await Promise.all([
  readFile('index.html', 'utf8'),
  readFile('worker.mjs', 'utf8'),
]);
await writeFile('dist/server/index.js', 'const PAGE = ' + JSON.stringify(page) + ';\n' + worker);
