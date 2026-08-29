import { expect, test } from '@playwright/test';

import { E2E_EMAIL } from '../playwright.config';
import { signIn } from './fixtures';

test.describe('signing in', () => {
  test('a valid login reaches the dashboard', async ({ page }) => {
    await signIn(page);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('a wrong password is refused and stores no token', async ({ page }) => {
    await page.goto('/login');
    await page.locator('#email').fill(E2E_EMAIL);
    await page.locator('#password').fill('definitely-not-the-password');
    await page.getByRole('button', { name: /sign in/i }).click();

    await expect(page).toHaveURL(/\/login/);
    // Asserting on storage as well as the URL: a form that shows an error but
    // keeps a token is the worse of the two bugs, and looks identical here.
    const storedToken = await page.evaluate(() =>
      Object.keys(localStorage).some((k) => localStorage.getItem(k)?.startsWith('eyJ')),
    );
    expect(storedToken).toBe(false);
  });

  test('a protected page redirects an anonymous visitor to login', async ({ page }) => {
    await page.goto('/trucks');
    await expect(page).toHaveURL(/\/login/);
  });

  test('the session survives a reload', async ({ page }) => {
    await signIn(page);
    await page.reload();
    await expect(page).toHaveURL(/\/dashboard/);
  });
});
