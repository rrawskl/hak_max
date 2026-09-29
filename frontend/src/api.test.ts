import { afterEach, expect, test, vi } from 'vitest';
import { authenticate, clearSession, request } from './api';

afterEach(() => { clearSession(); vi.unstubAllGlobals(); });

test('demo session sends a bearer token only after authentication', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ token: 'a-demo-token', mode: 'demo' }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 'me' }) });
  vi.stubGlobal('fetch', fetchMock);
  await authenticate();
  await request('/me');
  expect(fetchMock.mock.calls[0][0]).toContain('/auth/demo');
  expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe('Bearer a-demo-token');
});
