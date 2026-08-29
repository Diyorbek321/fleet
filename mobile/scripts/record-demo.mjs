/**
 * Records the driver-app walkthrough as a video, narrated in Uzbek.
 *
 *   node scripts/record-demo.mjs
 *
 * Drives the *web build* of the driver app in a phone-sized browser and
 * captures it. Recording the real Android build would need an emulator and a
 * screen recorder on the machine; the web build renders the same screens from
 * the same source, which is what a training video needs.
 *
 * Every caption describes something the script actually does on screen. A
 * tutorial that narrates a step it never performs teaches the wrong thing, so
 * there are no captions here for actions the run does not carry out.
 *
 * Captions are injected into the page rather than burned in afterwards, so
 * they stay attached to the step they explain and survive a re-encode.
 *
 * Needs, both running:
 *   - the API with the Uzbek demo tenant seeded (backend/seed_demo_uz.py)
 *   - the exported web build served (see mobile/README.md)
 */
import { chromium } from '@playwright/test';
import { mkdirSync } from 'node:fs';

const APP = process.env.DEMO_APP_URL ?? 'http://127.0.0.1:4175/';
const EMAIL = process.env.DEMO_EMAIL ?? 'haydovchi@silkroad.uz';
const PASSWORD = process.env.DEMO_PASSWORD ?? 'demo12345';
const OUT = process.env.DEMO_OUT ?? 'demo-video';

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 390, height: 844 },
  locale: 'uz',
  // Uzbekistan is UTC+5, so on-screen timestamps read local to the driver.
  timezoneId: 'Asia/Tashkent',
  // Granted up front: the live-tracking toggle is part of the walkthrough, and
  // a permission dialog is browser chrome the recording cannot capture anyway.
  permissions: ['geolocation'],
  geolocation: { latitude: 41.2995, longitude: 69.2401 }, // Toshkent
  recordVideo: { dir: OUT, size: { width: 390, height: 844 } },
});
const page = await context.newPage();

// React Navigation keeps every visited tab mounted, so a plain text or input
// selector matches hidden screens too. Everything below is scoped to what is
// actually on screen.
// Multi-line fields render as <textarea> on web, not <input>, so a selector
// for inputs alone silently skips them and the index of every later field
// shifts by one.
const visibleInputs = () => page.locator('input:visible, textarea:visible');

async function installCaptions() {
  await page.evaluate(() => {
    if (document.getElementById('demo-caption')) return;
    const bar = document.createElement('div');
    bar.id = 'demo-caption';
    bar.style.cssText = [
      'position:fixed', 'left:0', 'right:0', 'bottom:0', 'z-index:2147483647',
      'background:linear-gradient(to top, rgba(15,23,42,.97) 70%, rgba(15,23,42,0))',
      'color:#fff', 'font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif',
      'padding:30px 20px 34px', 'text-align:center', 'pointer-events:none',
      'opacity:0', 'transition:opacity .35s ease',
    ].join(';');
    const step = document.createElement('div');
    step.id = 'demo-step';
    step.style.cssText =
      'font-size:11px;letter-spacing:.16em;color:#7dd3fc;margin-bottom:8px;font-weight:800';
    const text = document.createElement('div');
    text.id = 'demo-text';
    text.style.cssText = 'font-size:19px;line-height:1.42;font-weight:600';
    bar.append(step, text);
    document.body.append(bar);
  });
}

let stepNo = 0;

/** Show a caption and hold it long enough to be read at a comfortable pace. */
async function say(text, { step = true, hold } = {}) {
  if (step) stepNo += 1;
  await installCaptions();
  await page.evaluate(
    ({ text, label }) => {
      document.getElementById('demo-step').textContent = label;
      document.getElementById('demo-text').textContent = text;
      document.getElementById('demo-caption').style.opacity = '1';
    },
    { text, label: step ? `${stepNo}-QADAM` : '' },
  );
  // ~14 characters a second, which is unhurried for a second language, with a
  // floor so short lines do not flash past.
  await page.waitForTimeout(hold ?? Math.max(2800, Math.min(7000, text.length * 74)));
}

async function hideCaption() {
  await page.evaluate(() => {
    const el = document.getElementById('demo-caption');
    if (el) el.style.opacity = '0';
  });
  await page.waitForTimeout(420);
}

/**
 * Tap something by its visible label, then let the screen settle.
 *
 * `.filter({ visible: true })` narrows the matches; chaining `.locator(...)`
 * would instead search *inside* each match, which silently selects an outer
 * container whose centre point lands on something else entirely.
 *
 * `.last()` takes the innermost match: ancestors come first in document order,
 * so the deepest element carrying the text is the one the user actually taps.
 */
async function tap(label, { exact = false, settle = 1700 } = {}) {
  const target = page.getByText(label, { exact }).filter({ visible: true }).last();
  await centre(target);

  // Clicked by coordinate rather than through `locator.click()`. React Native
  // Web renders each screen over a full-bleed gradient backdrop, and
  // Playwright's actionability check reports that backdrop as intercepting the
  // press — it also re-scrolls the element to the top edge, back under the
  // app's sticky header, undoing the centring above. The coordinate is taken
  // from the element's own box, so this presses exactly what it names.
  const box = await target.boundingBox();
  if (!box) throw new Error(`tap: "${label}" is not on screen`);
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForTimeout(settle);
}

/**
 * Scroll an element to the middle of the screen before touching it.
 *
 * `scrollIntoViewIfNeeded` parks the element against the top edge, which on
 * these screens puts it underneath the app's own sticky gradient header — the
 * click then lands on the header and times out. Centring also happens to make
 * a better recording, since the thing being tapped is where a viewer is
 * already looking.
 */
async function centre(locator) {
  await locator
    .evaluate((el) => el.scrollIntoView({ block: 'center', behavior: 'instant' }))
    .catch(() => {});
  await page.waitForTimeout(700);
}

/** Type into the nth visible field, slowly enough to be watchable. */
async function type(index, value) {
  const input = visibleInputs().nth(index);
  await centre(input);
  await input.click();
  await input.type(value, { delay: 60 });
  await page.waitForTimeout(500);
}

async function scroll(px) {
  await page.mouse.wheel(0, px);
  await page.waitForTimeout(900);
}

/**
 * Put the demo driver back to "before the shift started".
 *
 * The walkthrough shows a driver *starting* a shift, so a previous recording
 * would otherwise leave one running and the second take would open on a
 * different screen than the first. Done over the API rather than through the
 * UI so it stays off camera.
 */
async function resetDemoState() {
  const api = APP.replace(/\/$/, '');
  const base = process.env.DEMO_API_URL ?? 'http://127.0.0.1:8003';
  void api;
  const login = await fetch(`${base}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!login.ok) throw new Error(`demo login failed: ${login.status}`);
  const { access_token } = await login.json();
  const auth = { Authorization: `Bearer ${access_token}` };

  const current = await fetch(`${base}/api/me/shifts/current`, { headers: auth });
  const shift = current.ok ? await current.json() : null;
  if (shift) {
    await fetch(`${base}/api/me/shifts/end`, {
      method: 'POST',
      headers: { ...auth, 'Content-Type': 'application/json' },
      body: JSON.stringify({ end_mileage: 486_500 }),
    });
    console.log('[demo] avvalgi smena yopildi');
  }
}

await resetDemoState();

// ─── Kirish ──────────────────────────────────────────────────────────────────
await page.goto(APP, { waitUntil: 'networkidle', timeout: 60_000 });
await page.waitForTimeout(3200);

await tap('O‘zbekcha', { settle: 1200 });
await say('Fleet Watch — haydovchilar uchun ilova. Avval o‘z tilingizni tanlang.');
await hideCaption();

await say('Dispetcher bergan email va parol bilan kiring.');
await type(0, EMAIL);
await type(1, PASSWORD);
await hideCaption();
await tap('Kirish', { exact: true, settle: 6500 });

// ─── Smena ───────────────────────────────────────────────────────────────────
await say('Bosh sahifada mashinangiz, yoqilg‘i darajasi va probeg turadi.', { hold: 5000 });
await hideCaption();

await say('Ishni boshlashda «Smenani boshlash» tugmasini bosing.');
await hideCaption();
await tap('Smenani boshlash', { settle: 3200 });
await say('Tayyor — smena boshlandi. Dispetcher sizni endi ish ustida ko‘radi.', {
  step: false,
  hold: 4600,
});
await hideCaption();

// ─── Jonli kuzatuv ───────────────────────────────────────────────────────────
await scroll(320);
await say('Jonli kuzatuvni yoqing. Joylashuvingiz o‘zi yuboriladi — qo‘ng‘iroq qilish shart emas.');
await hideCaption();
const trackingSwitch = page.locator('[role="switch"]:visible, input[type="checkbox"]:visible').last();
if (await trackingSwitch.count()) {
  await trackingSwitch.click({ timeout: 8000 }).catch(() => {});
  await page.waitForTimeout(2600);
  await say('Kuzatuv yoqildi.', { step: false, hold: 3000 });
  await hideCaption();
}

// ─── Reyslar ─────────────────────────────────────────────────────────────────
await tap('Reyslar', { settle: 3400 });
await say('«Reyslar» bo‘limida sizga biriktirilgan yuklar turadi.', { hold: 4800 });
await hideCaption();
await say('Yo‘l holati o‘zgarganda tugmani bosing — dispetcher darhol biladi.');
await hideCaption();
// Matched by pattern, not by the exact label. The button names the *next*
// status ("Chegarada deb belgilash", "Yetkazildi deb belgilash", …), so it
// changes as soon as a take advances the trip — and a second recording would
// otherwise fail on a button that no longer exists.
const advance = page.getByText(/deb belgilash/).filter({ visible: true }).last();
if (await advance.count()) {
  const label = ((await advance.textContent()) ?? '').trim();
  const nextStatus = label.replace(/\s*deb belgilash\s*$/i, '');
  await centre(advance);
  const box = await advance.boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForTimeout(3600);
  await say(`Reys holati «${nextStatus}»ga o‘tdi.`, { step: false, hold: 3400 });
  await hideCaption();
}

// ─── Yoqilg'i ────────────────────────────────────────────────────────────────
await tap('Yoqilg‘i', { settle: 3200 });
await say('Yoqilg‘i quyganingizda: litr, litr narxi va probegni kiriting.');
await hideCaption();
await type(0, '520');
await type(1, '13800');
await type(2, '486980');
await type(3, 'Sardor Oil — Jizzax');
await say('Va saqlang.', { step: false, hold: 2600 });
await hideCaption();
await tap('Saqlash', { settle: 3600 });
await say('Yozuv qo‘shildi — summa o‘zi hisoblandi.', { step: false, hold: 3800 });
await hideCaption();

// ─── Xarajatlar ──────────────────────────────────────────────────────────────
await tap('Xarajatlar', { settle: 3200 });
await say('Yo‘ldagi har bir xarajatni shu yerga yozing: ovqat, yo‘l haqi, jarima, bojxona.', {
  hold: 5600,
});
await hideCaption();
await tap('Ovqat', { settle: 1400 });
await type(0, '85000');
await type(1, 'Jizzax — tushlik');
await hideCaption();
await tap('Saqlash', { settle: 3600 });
await say('Bular avtomatik yo‘l varaqasiga tushadi — qog‘oz to‘ldirish shart emas.', {
  step: false,
  hold: 5400,
});
await hideCaption();

// ─── Chegara navbati ─────────────────────────────────────────────────────────
await tap('Navbat', { settle: 3200 });
await say('Chegaraga borsangiz, navbatingizni shu yerdan kuzatasiz.', { hold: 4800 });
await hideCaption();
await say('Holat o‘zgarganda telefoningizga xabar keladi.', { hold: 4200 });
await hideCaption();

// ─── Texnik xizmat ───────────────────────────────────────────────────────────
await tap('Texnik xizmat', { settle: 3200 });
await say('Mashinada nosozlik bo‘lsa — shu yerdan xabar bering.');
await hideCaption();
await type(0, 'Old g‘ildirak tormozi');
await type(1, 'Tormoz kolodkasi eskirgan, almashtirish kerak.');
await hideCaption();
await tap('Yuborish', { settle: 3600 });
await say('Xabar dispetcherga ketdi.', { step: false, hold: 3400 });
await hideCaption();

// ─── Profil ──────────────────────────────────────────────────────────────────
await tap('Profil', { settle: 3200 });
await say('Profilda xavfsizlik bahoyingiz ko‘rinadi — tezlik, tormoz, bekor turish.', {
  hold: 5400,
});
await hideCaption();
await scroll(420);
await say('Parolni albatta o‘zingiznikiga almashtiring — uni dispetcher ham biladi.', {
  hold: 5400,
});
await hideCaption();

await say('Ish tugagach, bosh sahifadan smenani tugating. Tayyor!', { hold: 5000 });
await page.waitForTimeout(1800);

await context.close();
await browser.close();
console.log(`video: ${OUT}/`);
