import { test as base, expect, type Page } from '@playwright/test';

import { E2E_EMAIL, E2E_PASSWORD, E2E_SUPERADMIN } from '../playwright.config';

/**
 * Signs in through the real login form rather than injecting a token.
 *
 * Injecting one would skip the exact seam these tests exist to guard: that the
 * app and the API still agree on the login response and on what `/api/auth/me`
 * returns. It costs a couple of seconds per spec and is the point.
 */
export async function signIn(page: Page, email: string = E2E_EMAIL): Promise<void> {
  await page.goto('/login');
  await page.locator('#email').fill(email);
  await page.locator('#password').fill(E2E_PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  // A superadmin lands on /organizations, a company admin on /dashboard — the
  // app routes by role, so waiting for one specific path would fail for the
  // other. Either means the session is live.
  await expect(page).toHaveURL(/\/(dashboard|organizations)/, { timeout: 20_000 });
}

/** Sign in as the platform operator. */
export async function signInAsOperator(page: Page): Promise<void> {
  await signIn(page, E2E_SUPERADMIN);
}

export const test = base.extend<{ app: Page; operator: Page }>({
  app: async ({ page }, use) => {
    await signIn(page);
    await use(page);
  },
  // A separate fixture rather than a parameter: a spec is written for one role
  // or the other, and mixing them in one browser context invites a test that
  // passes because it is still signed in as somebody else.
  operator: async ({ page }, use) => {
    await signInAsOperator(page);
    await use(page);
  },
});

export { expect };

/** A value unique to this run, so re-running against a warm DB cannot collide. */
export function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
}
