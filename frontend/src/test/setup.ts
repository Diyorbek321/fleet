import '@testing-library/jest-dom/vitest';
import { beforeEach, vi } from 'vitest';

// Keep env predictable across tests
beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});
