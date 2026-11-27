const headers = { 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' };

function json(body, status = 200) {
  return Response.json(body, { status, headers });
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (path === '/' && request.method === 'GET') {
      return new Response(PAGE, {
        headers: { ...headers, 'content-type': 'text/html;charset=utf-8', 'referrer-policy': 'no-referrer' },
      });
    }
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
