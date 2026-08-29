import { expect, test } from './fixtures';

/**
 * The closing report — the document a customer sends to their accountant.
 *
 * The unit tests prove the arithmetic; nothing proved that the screen and the
 * API still agree on the shape of it, or that the download a user clicks
 * actually produces a workbook rather than an error page with a .xlsx name.
 */
test.describe('closing report', () => {
  test('the period card renders its figures', async ({ app }) => {
    await app.goto('/reports');

    const card = app.getByText(/yakuniy hisobot|closing report|итоговый отчёт/i).first();
    await expect(card).toBeVisible();

    // The four figures the report exists for. Their values depend on seeded
    // history the E2E database does not have; that they render at all is the
    // contract this guards.
    for (const label of [/daromad|revenue|выручка/i, /foyda|profit|прибыль/i]) {
      await expect(app.getByText(label).first()).toBeVisible();
    }
  });

  test('switching period reloads the figures', async ({ app }) => {
    await app.goto('/reports');

    const lastMonth = app.getByRole('button', { name: /o‘tgan oy|last month|прошлый месяц/i });
    await expect(lastMonth).toBeVisible();

    const before = await app.getByText(/·/).first().textContent();
    await lastMonth.click();
    // The header carries the period label and its exact dates, so a change
    // there proves the request went out and came back with a different period.
    await expect(async () => {
      const after = await app.getByText(/·/).first().textContent();
      expect(after).not.toBe(before);
    }).toPass({ timeout: 15_000 });
  });

  test('the Excel download is a real workbook', async ({ app }) => {
    await app.goto('/reports');

    const download = app.waitForEvent('download', { timeout: 30_000 });
    await app.getByRole('button', { name: /^excel$/i }).click();
    const file = await download;

    // The server names the file; a client-side fallback name would mean the
    // Content-Disposition header never arrived.
    expect(file.suggestedFilename()).toMatch(/^hisobot-(oylik|haftalik)-\d{4}-\d{2}-\d{2}\.xlsx$/);

    const path = await file.path();
    expect(path).toBeTruthy();

    // PK is the zip magic every xlsx starts with. An error page saved under an
    // .xlsx name is the failure this catches, and it looks identical until
    // someone tries to open it.
    const fs = await import('node:fs');
    const head = fs.readFileSync(path!).subarray(0, 2).toString('latin1');
    expect(head).toBe('PK');
  });
});
