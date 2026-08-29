import { expect, test, unique } from './fixtures';

test.describe('trucks', () => {
  test('a new truck is created and shows up in the list', async ({ app }) => {
    const plate = unique('E2E').toUpperCase();
    const name = `Truck ${plate}`;

    await app.goto('/trucks');
    await app.getByRole('button', { name: /add new truck/i }).click();

    await app.getByPlaceholder('ABC 1234').fill(plate);
    await app.getByPlaceholder(/Freightliner Cascadia/i).fill(name);
    await app.getByPlaceholder(/GPS tracker IMEI/i).fill(String(Date.now()).padStart(15, '3'));

    await app.getByRole('button', { name: /^(add|save|create)/i }).last().click();

    // Exact match: the list renders the plate on its own AND inside the truck
    // name, so a loose match resolves to two nodes and fails on strictness
    // rather than on anything real.
    await expect(app.getByText(plate, { exact: true })).toBeVisible();

    // Reload rather than trusting the optimistic update: this test exists to
    // prove the row reached the database, not that the client re-rendered.
    await app.reload();
    await expect(app.getByText(plate, { exact: true })).toBeVisible();
  });

  test('the truck list survives a reload without an error state', async ({ app }) => {
    await app.goto('/trucks');
    await expect(app.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(app.getByText(/failed|error/i)).toHaveCount(0);
  });
});
