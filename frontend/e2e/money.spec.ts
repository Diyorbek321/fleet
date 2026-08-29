import { expect, test } from './fixtures';

/**
 * The money screens.
 *
 * These are what the product is sold on, and they are the ones a broken API
 * contract quietly empties: the request 200s with a shape the client cannot
 * read, every figure renders as zero or a dash, and nothing anywhere errors.
 * So the assertions are about *reaching* real numbers, not about their values,
 * which depend on seeded history these tests deliberately do not create.
 */
test.describe('money screens', () => {
  test('the dashboard renders its figures', async ({ app }) => {
    await app.goto('/dashboard');
    await expect(app.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(app.getByText(/failed to|error/i)).toHaveCount(0);
  });

  test('the leakage page loads its summary', async ({ app }) => {
    await app.goto('/leakage');
    await expect(app.getByRole('heading', { name: /leakage/i })).toBeVisible();
    // The three headline cards are the page. If the summary call broke, they
    // are the first thing to disappear.
    // .first(): each label appears on its headline card and again as a section
    // heading further down the page.
    await expect(app.getByText(/fuel waste/i).first()).toBeVisible();
    await expect(app.getByText(/unauthorized stops/i).first()).toBeVisible();
    await expect(app.getByText(/idle hours/i).first()).toBeVisible();
  });

  test('the reports page loads', async ({ app }) => {
    await app.goto('/reports');
    await expect(app.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(app.getByText(/failed to load/i)).toHaveCount(0);
  });
});
