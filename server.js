import http from 'node:http';
import { DatabaseSync } from 'node:sqlite';
import { mkdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.dirname(fileURLToPath(import.meta.url));
const statuses = ['Yeni', 'İnceleniyor', 'Görüşme', 'İzlemede', 'Pas'];
export function createApp(filename = process.env.DB_PATH || path.join(root, 'data/scout.db')) {
  if (filename !== ':memory:') mkdirSync(path.dirname(filename), { recursive: true });
  const db = new DatabaseSync(filename);
  db.exec(`PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS startups (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, sector TEXT NOT NULL, stage TEXT NOT NULL,
    location TEXT NOT NULL, website TEXT NOT NULL, description TEXT NOT NULL,
    score INTEGER NOT NULL, status TEXT NOT NULL, notes TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)`);
  const send = (res, code, body) => { res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8' }); res.end(JSON.stringify(body)); };
  const server = http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url, 'http://localhost');
      if (url.pathname === '/api/health') return send(res, 200, { status: 'ok' });
      if (url.pathname === '/api/startups' && req.method === 'GET') {
        return send(res, 200, db.prepare('SELECT * FROM startups ORDER BY score DESC, id DESC').all());
      }
      const match = url.pathname.match(/^\/api\/startups\/(\d+)$/);
      if ((url.pathname === '/api/startups' && req.method === 'POST') || (match && req.method === 'PUT')) {
        let raw = '';
        for await (const chunk of req) { raw += chunk; if (raw.length > 32768) return send(res, 413, { error: 'Kayıt çok büyük.' }); }
        let input; try { input = JSON.parse(raw); } catch { return send(res, 400, { error: 'Geçersiz JSON.' }); }
        if (!input || typeof input !== 'object') return send(res, 400, { error: 'Geçersiz kayıt.' });
        const fields = ['name', 'sector', 'stage', 'location', 'website', 'description', 'status', 'notes'];
        const item = Object.fromEntries(fields.map(k => [k, typeof input[k] === 'string' ? input[k].trim() : '']));
        const score = input.score;
        if (!item.name || !item.sector || !item.stage || !statuses.includes(item.status) || !Number.isInteger(score) || score < 0 || score > 100 || fields.some(k => item[k].length > 5000)) return send(res, 400, { error: 'Ad, sektör, aşama, durum ve 0–100 arasında tam sayı puan gerekli.' });
        if (item.website) {
          try { const website = new URL(item.website); if (!['http:', 'https:'].includes(website.protocol)) throw Error(); } catch { return send(res, 400, { error: 'Web sitesi http:// veya https:// ile başlamalı.' }); }
        }
        const values = [...fields.map(k => item[k]), score];
        let id;
        if (match) {
          id = Number(match[1]);
          const result = db.prepare(`UPDATE startups SET ${fields.map(k => `${k}=?`).join(',')},score=? WHERE id=?`).run(...values, id);
          if (!result.changes) return send(res, 404, { error: 'Girişim bulunamadı.' });
        } else {
          id = Number(db.prepare(`INSERT INTO startups (${fields.join(',')},score) VALUES (${values.map(() => '?').join(',')})`).run(...values).lastInsertRowid);
        }
        return send(res, match ? 200 : 201, db.prepare('SELECT * FROM startups WHERE id=?').get(id));
      }
      if (match && req.method === 'DELETE') {
        const result = db.prepare('DELETE FROM startups WHERE id=?').run(Number(match[1]));
        return send(res, result.changes ? 200 : 404, result.changes ? { deleted: true } : { error: 'Girişim bulunamadı.' });
      }
      const files = { '/': ['index.html', 'text/html'], '/app.js': ['app.js', 'text/javascript'], '/style.css': ['style.css', 'text/css'] };
      if (req.method === 'GET' && files[url.pathname]) {
        const [file, type] = files[url.pathname];
        res.writeHead(200, { 'Content-Type': `${type}; charset=utf-8`, 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'self'; style-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'" });
        return res.end(readFileSync(path.join(root, 'public', file)));
      }
      send(res, 404, { error: 'Bulunamadı.' });
    } catch (err) { console.error(err); send(res, 500, { error: 'İşlem tamamlanamadı.' }); }
  });
  server.on('close', () => db.close());
  return server;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.PORT || 3000);
  createApp().listen(port, process.env.HOST || '127.0.0.1', () => console.log(`Scout AI listening on port ${port}`));
}
