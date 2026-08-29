import { expect, test } from './fixtures';

/**
 * The operator console: the overview, support access, and the audit trail.
 *
 * Support access punches a hole in the isolation boundary the rest of the app
 * exists to hold, so what is checked here is mostly the fence around it — and
 * in particular that leaving a session really does put the operator back in
 * their own empty organization rather than leaving a customer's cached data
 * on screen under their own name.
 */
test.describe('operator console', () => {
  test('the platform overview shows the book of business', async ({ operator }) => {
    await operator.goto('/organizations');

    await expect(operator.getByText(/platforma|platform|платформа/i).first()).toBeVisible();
    await expect(
      operator.getByText(/kompaniyalar|companies|компании/i).first(),
    ).toBeVisible();
    await expect(operator.getByText(/audit|журнал/i).first()).toBeVisible();
  });

  test('onboarding a company is recorded in the audit log', async ({ operator }) => {
    const name = `E2E Co ${Date.now().toString(36)}`;

    await operator.goto('/organizations');
    await operator.getByRole('button', { name: /qo‘shish|add|добавить/i }).first().click();

    // By id, not by index: the dialog's second and third inputs are the
    // optional contact name and phone, so filling positionally put the admin
    // email into the contact field and created nothing.
    const dialog = operator.getByRole('dialog');
    await dialog.locator('#org-name').fill(name);
    await dialog.locator('#org-admin-email').fill(`admin-${Date.now().toString(36)}@e2e-co.com`);
    await dialog.locator('#org-admin-password').fill('password123');
    // By type, not by label: the submit button reads `common.save`, so a
    // pattern built from create/add words matched neither it nor Cancel, and
    // the click waited out its timeout on nothing.
    await dialog.locator('button[type="submit"]').click();

    // The company appears, and so does the record of creating it — which is
    // the half no screen inside the customer's own account would ever show.
    await expect(operator.getByText(name).first()).toBeVisible({ timeout: 15_000 });
    await expect(operator.getByText('organization.create').first()).toBeVisible({
      timeout: 15_000,
    });
  });

  test('a support session opens the customer and can be left again', async ({ operator }) => {
    await operator.goto('/organizations');

    // Targeted by name, not by position. The list is newest-first and the
    // operator's own Platform organization is seeded last, so the first row is
    // the one whose eye button is deliberately disabled.
    const customerRow = operator.locator('tbody tr').filter({ hasText: 'E2E Logistics' });
    await expect(customerRow).toBeVisible({ timeout: 15_000 });
    await customerRow.locator('button').first().click();

    // Entering is a full page load by design, so wait for the destination.
    await expect(operator).toHaveURL(/\/dashboard/, { timeout: 25_000 });
    const banner = operator.getByText(/qo‘llab-quvvatlash|support session|сеанс поддержки/i);
    await expect(banner.first()).toBeVisible({ timeout: 15_000 });

    await operator.getByRole('button', { name: /chiqish|exit|выйти/i }).first().click();
    await expect(operator).toHaveURL(/\/organizations/, { timeout: 25_000 });
    await expect(banner.first()).toHaveCount(0);
  });

  test('a company admin never sees the operator console', async ({ app }) => {
    await app.goto('/organizations');
    // RoleRoute sends them away rather than rendering an empty console.
    await expect(app).not.toHaveURL(/\/organizations/, { timeout: 15_000 });
  });
});
