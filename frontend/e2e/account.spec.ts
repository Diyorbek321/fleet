import { expect, test } from '@playwright/test';

import { E2E_API_URL, E2E_EMAIL, E2E_PASSWORD } from '../playwright.config';
import { signIn } from './fixtures';

/**
 * Changing your own password.
 *
 * The server invalidates every token minted under the old password — including
 * the one that made the request — and hands back a replacement pair. If the
 * client fails to store those, the user is signed out for having done the
 * right thing, which a unit test with a mocked fetch cannot see.
 *
 * The first test provisions a throwaway colleague and changes *their*
 * password. An earlier version changed the shared E2E admin's, which meant
 * this file — first alphabetically, and so first to run — silently broke the
 * sign-in of every spec after it.
 */
test.describe('account', () => {
  test('changing the password keeps this session signed in', async ({ page, request }) => {
    await signIn(page);

    // Provisioned over the API rather than through the UI: the subject here is
    // the password dialog, not the user-creation form.
    const tag = `${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
    const email = `pw-${tag}@fleetwatch-e2e.com`;
    const password = 'colleague-pass-1';
    const token = await page.evaluate(() => localStorage.getItem('fleet_access_token'));

    const made = await request.post(`${E2E_API_URL}/api/auth/users`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { email, password, role: 'operator' },
    });
    expect(made.status()).toBe(201);

    await page.goto('/login');
    await page.evaluate(() => localStorage.clear());
    await page.goto('/login');
    await page.locator('#email').fill(email);
    await page.locator('#password').fill(password);
    await page.getByRole('button', { name: /sign in/i }).click();
    await expect(page).toHaveURL(/\/(dashboard|organizations)/, { timeout: 20_000 });

    await page.goto('/settings');
    await page
      .getByRole('button', { name: /parolni o‘zgartirish|change password|сменить пароль/i })
      .first()
      .click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    const fields = dialog.locator('input[type="password"]');
    const next = `changed-${tag}`;
    await fields.nth(0).fill(password);
    await fields.nth(1).fill(next);
    await fields.nth(2).fill(next);
    await dialog.locator('button[type="submit"]').click();

    await expect(dialog).toHaveCount(0, { timeout: 20_000 });

    // Still signed in and still able to reach an authenticated screen — which
    // it would not be if the re-issued tokens had been dropped.
    await page.goto('/trucks');
    await expect(page).toHaveURL(/\/trucks/);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('the wrong current password is refused', async ({ page }) => {
    // Safe to run as the shared admin: this attempt is meant to fail, so their
    // password is never actually changed — and the last assertion proves it.
    await signIn(page);
    await page.goto('/settings');
    await page
      .getByRole('button', { name: /parolni o‘zgartirish|change password|сменить пароль/i })
      .first()
      .click();

    const dialog = page.getByRole('dialog');
    const fields = dialog.locator('input[type="password"]');
    await fields.nth(0).fill('definitely-not-the-password');
    await fields.nth(1).fill('some-new-password');
    await fields.nth(2).fill('some-new-password');
    await dialog.locator('button[type="submit"]').click();

    // The dialog stays open with an error rather than closing on a failure.
    await expect(dialog).toBeVisible();

    await page.goto('/login');
    await page.evaluate(() => localStorage.clear());
    await page.goto('/login');
    await page.locator('#email').fill(E2E_EMAIL);
    await page.locator('#password').fill(E2E_PASSWORD);
    await page.getByRole('button', { name: /sign in/i }).click();
    await expect(page).toHaveURL(/\/(dashboard|organizations)/, { timeout: 20_000 });
  });
});
