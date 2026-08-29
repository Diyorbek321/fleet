import { test as base, expect, type Page } from '@playwright/test';

import { E2E_EMAIL, E2E_PASSWORD } from '../playwright.config';

/**
 * Signs in through the real login form rather than injecting a token.
 *
 * Injecting one would skip the exact seam these tests exist to guard: that the
 * app and the API still agree on the login response and on what `/api/auth/me`
 * returns. It costs a couple of seconds per spec and is the point.
 */
export async function signIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.locator('#email').fill(E2E_EMAIL);
  await page.locator('#password').fill(E2E_PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 20_000 });
}

export const test = base.extend<{ app: Page }>({
  app: async ({ page }, use) => {
    await signIn(page);
    await use(page);
  },
});

export { expect };

/** A value unique to this run, so re-running against a warm DB cannot collide. */
export function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
}
