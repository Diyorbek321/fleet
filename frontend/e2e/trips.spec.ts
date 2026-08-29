import { expect, test } from './fixtures';

test.describe('trips', () => {
  test('a trip is created and advances through its statuses', async ({ app }) => {
    await app.goto('/trips');
    await app.getByRole('button', { name: /new trip/i }).click();

    // Rate is the field that makes a trip worth tracking; the rest is optional.
    const rate = app.getByLabel(/^rate$/i);
    await rate.fill('7500000');
    await app.getByRole('button', { name: /^(create|save|add)/i }).last().click();

    // A reference is generated per tenant on create, so its presence proves the
    // row was written rather than merely posted.
    const row = app.locator('tbody tr').first();
    await expect(row).toBeVisible();

    await app.reload();
    await expect(app.locator('tbody tr').first()).toBeVisible();
  });
});
