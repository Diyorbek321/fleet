/**
 * Navigation performance probe.
 *
 *   npm run perf            # against a preview build on :4174
 *   PERF_THROTTLE=0 npm run perf   # unthrottled, for comparison
 *
 * Clicks through the sidebar and reports, per route, how long until the page's
 * heading is on screen and how many API calls it cost. Run it before and after
 * a change; the numbers are the only honest way to tell an optimisation from a
 * rearrangement.
 *
 * Two things it does deliberately:
 *
 * - It *clicks* rather than calling page.goto. goto reloads the whole app,
 *   which is not what "switching between pages" means and is not what anyone
 *   does twice in a session.
 * - It throttles to what the production droplet actually delivers (~46 KB/s,
 *   ~150 ms RTT, measured with curl against fleet.eduly.uz) and slows the CPU
 *   4x. Unthrottled on localhost every route already rendered in 40-105 ms
 *   while the app felt slow to the user — the default numbers say nothing.
 *
 * Needs a backend with data and a preview build pointed at it. See
 * backend/e2e_server.py for the throwaway-database pattern, or point
 * PERF_BASE / PERF_EMAIL / PERF_PASSWORD at any instance.
 */
import { chromium } from '@playwright/test';

const BASE = process.env.PERF_BASE ?? 'http://127.0.0.1:4174';
const EMAIL = process.env.PERF_EMAIL ?? 'demo@silkroad.uz';
const PASSWORD = process.env.PERF_PASSWORD ?? 'perfpassword123';
const ROUNDS = Number(process.env.PERF_ROUNDS ?? 3);
const LABEL = process.env.PERF_LABEL ?? 'run';

const ROUTES = ['Dashboard', 'Trucks', 'Trips', 'Leakage', 'Reports', 'Drivers'];

const browser = await chromium.launch();
const context = await browser.newContext();
const page = await context.newPage();

// Throttle to what the droplet actually delivers from here: ~46 KB/s down and
// a ~150 ms round trip, measured with curl against fleet.eduly.uz. Unthrottled
// localhost numbers say nothing about a user in Tashkent on a real link — the
// app was already "fast" at 40 ms per navigation while the user was waiting
// seconds.
if (process.env.PERF_THROTTLE !== '0') {
  const cdp = await context.newCDPSession(page);
  await cdp.send('Network.emulateNetworkConditions', {
    offline: false,
    latency: Number(process.env.PERF_LATENCY ?? 150),
    downloadThroughput: Number(process.env.PERF_DOWN ?? 46 * 1024),
    uploadThroughput: Number(process.env.PERF_UP ?? 20 * 1024),
  });
  // A mid-range Android phone or an old office laptop, which is what a
  // dispatcher actually uses.
  await cdp.send('Emulation.setCPUThrottlingRate', {
    rate: Number(process.env.PERF_CPU ?? 4),
  });
}

let apiCalls = 0;
page.on('request', (r) => {
  if (r.url().includes('/api/')) apiCalls++;
});

await page.goto(`${BASE}/login`);
await page.locator('#email').fill(EMAIL);
await page.locator('#password').fill(PASSWORD);
await page.getByRole('button', { name: /sign in/i }).click();
await page.waitForURL(/\/dashboard/, { timeout: 30000 });
await page.waitForLoadState('networkidle').catch(() => {});

const results = new Map();

for (let round = 0; round < ROUNDS; round++) {
  for (const name of ROUTES) {
    const before = apiCalls;
    const t0 = Date.now();
    await page.getByRole('link', { name, exact: true }).first().click();
    await page.getByRole('heading', { level: 1 }).first().waitFor({ timeout: 30000 });
    const painted = Date.now() - t0;
    await page.waitForLoadState('networkidle').catch(() => {});
    const settled = Date.now() - t0;

    // Round 0 is the cold pass: each lazy chunk is fetched for the first time.
    // Later rounds are the repeat visit, which is what "switching between
    // pages" actually means once you have been in the app for a minute.
    const key = round === 0 ? `${name} (first)` : name;
    if (!results.has(key)) results.set(key, []);
    results.get(key).push({ painted, settled, api: apiCalls - before });
  }
}

const median = (xs) => xs.slice().sort((a, b) => a - b)[Math.floor(xs.length / 2)];

console.log(`\n=== ${LABEL} ===`);
console.log('route                heading   settled   api calls');
console.log('-'.repeat(52));
for (const [name, runs] of results) {
  console.log(
    name.padEnd(20) +
      `${median(runs.map((r) => r.painted))}ms`.padStart(8) +
      `${median(runs.map((r) => r.settled))}ms`.padStart(10) +
      `${median(runs.map((r) => r.api))}`.padStart(11),
  );
}
console.log('-'.repeat(52));
console.log(`total API calls across ${ROUNDS} rounds: ${apiCalls}`);

await browser.close();
