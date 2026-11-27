const headers = { 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' };

function json(body, status = 200) {
  return Response.json(body, { status, headers });
}

async function readJSON(request) {
  const reader = request.body?.getReader();
  if (!reader) return json({ error: 'Expected a snapshot' }, 400);
  const decoder = new TextDecoder();
  let bytes = 0;
  let payload = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    bytes += value.byteLength;
    if (bytes > 600_000) {
      await reader.cancel();
      return json({ error: 'Snapshot too large' }, 413);
    }
    payload += decoder.decode(value, { stream: true });
  }
  payload += decoder.decode();
  let snapshot;
  try { snapshot = JSON.parse(payload); } catch { return json({ error: 'Invalid JSON' }, 400); }
  return { snapshot, payload };
}

const isoDay = /^\d{4}-\d{2}-\d{2}$/;

async function daily(request, db) {
  const day = new URL(request.url).searchParams.get('day');
  if (request.method === 'GET') {
    if (day === null) {
      const dates = await db.prepare('SELECT day, closed FROM lab_daily_report ORDER BY day DESC LIMIT 365').all();
      return json({ days: dates.results });
    }
    if (!isoDay.test(day)) return json({ error: 'Invalid day' }, 400);
    const row = await db.prepare('SELECT payload FROM lab_daily_report WHERE day = ?').bind(day).first();
    return row ? new Response(row.payload, {headers: {...headers, 'content-type': 'application/json'}})
      : json({ error: 'No report for that day' }, 404);
  }
  if (request.method !== 'PUT') return json({ error: 'Method not allowed' }, 405);
  if (request.headers.has('oai-authenticated-user-id')) return json({ error: 'Service access required' }, 403);
  const body = await readJSON(request);
  if (body instanceof Response) return body;
  const { snapshot: report, payload } = body;
  if (typeof report?.day !== 'string' || !isoDay.test(report.day) || typeof report.closed !== 'boolean' ||
      report.timezone !== 'Asia/Kolkata' || !Array.isArray(report.work) ||
      !Array.isArray(report.agents) || !Array.isArray(report.collaborations) || !report.counts) {
    return json({ error: 'Invalid daily report' }, 400);
  }
  await db.prepare(
    'INSERT INTO lab_daily_report (day, closed, payload) VALUES (?, ?, ?) ' +
    'ON CONFLICT(day) DO UPDATE SET closed = excluded.closed, payload = excluded.payload ' +
    'WHERE excluded.closed >= lab_daily_report.closed',
  ).bind(report.day, Number(report.closed), payload).run();
  return json({ day: report.day });
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (path === '/' && request.method === 'GET') {
      return new Response(PAGE, {
        headers: { ...headers, 'content-type': 'text/html;charset=utf-8', 'referrer-policy': 'no-referrer' },
      });
    }
    if (path === '/api/daily') return daily(request, env.DB);
    if (path !== '/api/lab') return json({ error: 'Unknown path' }, 404);
    if (request.method === 'GET') {
      const snapshot = await env.DB.prepare('SELECT payload FROM lab_snapshot WHERE id = 1').first();
      return snapshot ? new Response(snapshot.payload, {
        headers: { ...headers, 'content-type': 'application/json' },
      }) : json({ runs: [], intervalHours: 6, revision: 0 });
    }
    if (request.method !== 'PUT') return json({ error: 'Method not allowed' }, 405);
    // Sites consumes the service bearer at its private perimeter. A browser's
    // signed-in identity is never used as a service writer.
    if (request.headers.has('oai-authenticated-user-id')) return json({ error: 'Service access required' }, 403);
    const body = await readJSON(request);
    if (body instanceof Response) return body;
    const { snapshot, payload } = body;
    if (!Number.isSafeInteger(snapshot?.revision) || snapshot.revision <= 0 ||
        !Array.isArray(snapshot.runs) || snapshot.runs.length > 24 ||
        snapshot.runs.some(run => !run || !Array.isArray(run.events))) {
      return json({ error: 'Invalid snapshot' }, 400);
    }
    const update = await env.DB.prepare(
      'INSERT INTO lab_snapshot (id, revision, payload) VALUES (1, ?, ?) ' +
      'ON CONFLICT(id) DO UPDATE SET revision = excluded.revision, payload = excluded.payload ' +
      'WHERE excluded.revision > lab_snapshot.revision',
    ).bind(snapshot.revision, payload).run();
    return json({ accepted: update.meta.changes === 1 });
  },
};
