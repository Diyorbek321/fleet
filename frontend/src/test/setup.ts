import '@testing-library/jest-dom/vitest';
import { beforeEach, vi } from 'vitest';

// Radix primitives (Select, Dialog, Popover) measure their trigger on mount and
// call scrollIntoView on the active item. jsdom implements neither, so without
// these stubs any page containing one throws before a single assertion runs.
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

// Keep env predictable across tests
beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});
