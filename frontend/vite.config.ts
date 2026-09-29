import { defineConfig } from 'vitest/config';

export default defineConfig({
  server: { host: '0.0.0.0', proxy: { '/api': 'http://localhost:8000', '/health': 'http://localhost:8000' } },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts', 'src/**/*.test.tsx'] },
});
