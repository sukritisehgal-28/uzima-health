import assert from 'node:assert/strict';
import { test } from 'node:test';
import handler from '../api/relay.js';

function response() {
  return { headers: {}, code: 200, body: undefined,
    setHeader(name, value) { this.headers[name] = value; },
    status(code) { this.code = code; return this; },
    json(value) { this.body = value; return this; },
    send(value) { this.body = value; return this; } };
}

test('relay rejects private backend routes', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = () => { throw new Error('Must not contact backend'); };
  try {
    for (const url of ['/api/call', '/api/bridge', '/api/outbox', '/api/transfers/invalid/accept']) {
      const res = response();
      await handler({ url, method: 'POST', headers: {} }, res);
      assert.equal(res.code, 404);
    }
  } finally { globalThis.fetch = original; }
});

test('relay forwards allowed requests and preserves failed upstream status', async () => {
  const original = globalThis.fetch;
  const previousOrigin = process.env.UZIMA_BACKEND_URL;
  process.env.UZIMA_BACKEND_URL = 'https://backend.example';
  globalThis.fetch = async (url, init) => {
    assert.equal(url, 'https://backend.example/dashboard/transfers/abcdef1234/accept');
    assert.equal(init.headers.Authorization, undefined);
    assert.equal(init.body, '{"hospital_id":"demo"}');
    assert.equal(init.redirect, 'error');
    return new Response('{"detail":"no available hospital"}', { status: 409 });
  };
  try {
    const res = response();
    await handler({ url: '/api/relay?path=transfers/abcdef1234/accept', query: { path: 'transfers/abcdef1234/accept' }, method: 'POST', headers: {}, body: { hospital_id: 'demo' } }, res);
    assert.equal(res.code, 409);
    assert.equal(res.headers['Cache-Control'], 'no-store');
    assert.match(res.body, /no available hospital/);
  } finally {
    globalThis.fetch = original;
    if (previousOrigin === undefined) delete process.env.UZIMA_BACKEND_URL;
    else process.env.UZIMA_BACKEND_URL = previousOrigin;
  }
});

test('relay reports offline backend without revealing internal errors', async () => {
  const original = globalThis.fetch;
  const previousOrigin = process.env.UZIMA_BACKEND_URL;
  process.env.UZIMA_BACKEND_URL = 'https://backend.example';
  globalThis.fetch = async () => { throw new Error('private upstream details'); };
  try {
    const res = response();
    await handler({ url: '/api/health', method: 'GET', headers: {} }, res);
    assert.equal(res.code, 503);
    assert.match(res.body.detail, /offline/);
    assert.doesNotMatch(JSON.stringify(res.body), /private/);
  } finally {
    globalThis.fetch = original;
    if (previousOrigin === undefined) delete process.env.UZIMA_BACKEND_URL;
    else process.env.UZIMA_BACKEND_URL = previousOrigin;
  }
});
