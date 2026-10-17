import "@testing-library/jest-dom/vitest";

// jsdom has no ResizeObserver; components that measure themselves (the critical
// banner publishes its height so map controls clear it) need one to mount at all.
class StubResizeObserver implements ResizeObserver {
  observe(): void {
    /* measurements are a browser concern; nothing to report in jsdom */
  }
  unobserve(): void {}
  disconnect(): void {}
}
// TypeScript declares ResizeObserver as always present; in jsdom it is not.
if (!("ResizeObserver" in globalThis)) globalThis.ResizeObserver = StubResizeObserver;
