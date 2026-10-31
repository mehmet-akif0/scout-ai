import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createApp } from '../server.js';
const item = { name: 'Örnek Girişim', sector: 'Fintech', stage: 'Seed', location: 'İstanbul', website: 'https://example.com', description: 'Ödeme altyapısı', score: 85, status: 'Yeni', notes: 'Ekiple görüş' };
async function start(file) {
  const server = createApp(file);
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return { server, url: `http://127.0.0.1:${server.address().port}` };
}
const close = server => new Promise(resolve => server.close(resolve));
test('CRUD, validation, static assets and durable SQLite storage', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'scout-test-'));
  const file = path.join(dir, 'test.db');
  let app = await start(file);
  const request = (route, method, body) => fetch(app.url + route, { method, headers: { 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  try {
    assert.equal((await request('/api/health')).status, 200);
    const page = await request('/'); assert.match(await page.text(), /Girişim radarı/);
    for (const route of ['/app.js', '/style.css']) assert.equal((await request(route)).status, 200);
    assert.deepEqual(await (await request('/api/startups')).json(), []);
    for (const invalid of [{ ...item, score: 101 }, { ...item, name: '' }, { ...item, website: 'javascript:alert(1)' }, { ...item, status: 'Unknown' }, null]) assert.equal((await request('/api/startups', 'POST', invalid)).status, 400);
    const created = await request('/api/startups', 'POST', item); assert.equal(created.status, 201);
    const saved = await created.json(); assert.equal(saved.name, item.name);
    const updated = await request(`/api/startups/${saved.id}`, 'PUT', { ...item, status: 'Görüşme', notes: '<script>test</script>' }); assert.equal(updated.status, 200);
    await close(app.server); app = await start(file);
    const rows = await (await request('/api/startups')).json(); assert.equal(rows.length, 1); assert.equal(rows[0].status, 'Görüşme'); assert.equal(rows[0].notes, '<script>test</script>');
    assert.equal((await request('/api/startups/9999', 'PUT', item)).status, 404);
    assert.equal((await request(`/api/startups/${saved.id}`, 'DELETE')).status, 200);
    assert.deepEqual(await (await request('/api/startups')).json(), []);
    assert.equal((await request(`/api/startups/${saved.id}`, 'DELETE')).status, 404);
  } finally { await close(app.server); rmSync(dir, { recursive: true, force: true }); }
});
