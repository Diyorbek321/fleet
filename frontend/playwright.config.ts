import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end coverage of the money path.
 *
 * The unit suite mocks `fetch`, so it proves the client's own logic and
 * nothing about whether the app and the API still agree. These tests drive the
 * real UI against a real backend and a real database, which is the only place a
 * renamed field or a changed status code actually shows up.
 *
 * Both servers are started here rather than assumed: an E2E suite that needs a
 * README to run is one nobody runs. `e2e_server.py` rebuilds a throwaway
 * database from the migration chain and seeds one admin — see its docstring.
 */
const API_PORT = Number(process.env.E2E_PORT ?? 8001);
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 4173);

export const E2E_API_URL = `http://127.0.0.1:${API_PORT}`;
export const E2E_EMAIL = process.env.E2E_EMAIL ?? 'e2e@fleetwatch-e2e.com';
export const E2E_PASSWORD = process.env.E2E_PASSWORD ?? 'e2e-password-123';

export default defineConfig({
  testDir: './e2e',
  // Serial. The suite shares one seeded organization, and the money screens
  // assert on fleet-wide totals that a parallel worker creating trucks would
  // change underneath them.
  workers: 1,
  fullyParallel: false,
  // A flake here is a signal, not noise: these run against a database rebuilt
  // from scratch, so there is nothing left for a retry to smooth over.
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      // Prefer the local virtualenv, fall back to python3. CI installs the
      // backend's requirements into the system interpreter and has no .venv,
      // while a developer's machine has the venv and usually no `python` on
      // PATH at all — this runs unchanged in both. Override with E2E_PYTHON.
      command:
        process.env.E2E_PYTHON
          ? `${process.env.E2E_PYTHON} e2e_server.py`
          : 'if [ -x .venv/bin/python ]; then .venv/bin/python e2e_server.py; else python3 e2e_server.py; fi',
      cwd: '../backend',
      url: `${E2E_API_URL}/health`,
      // Never reuse: the script drops and recreates its database on boot, so a
      // leftover server from an earlier run would serve stale state that the
      // specs' fixtures silently build on.
      reuseExistingServer: false,
      // Migrations from zero, then a seed. Slower than a server that just boots.
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
      env: { E2E_PORT: String(API_PORT), E2E_EMAIL, E2E_PASSWORD },
    },
    {
      // `preview` serves the production build, so these test the bundle that
      // actually ships rather than the dev server's transformed modules.
      command: `npm run build && npm run preview -- --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: {
        VITE_API_URL: E2E_API_URL,
        VITE_WS_URL: E2E_API_URL.replace('http', 'ws'),
      },
    },
  ],
});
