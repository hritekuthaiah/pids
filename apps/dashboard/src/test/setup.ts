import "@testing-library/jest-dom/vitest";

/**
 * jsdom has no ResizeObserver, so components that measure themselves (the critical
 * banner publishes its height so map controls clear it) cannot mount without one.
 * This reports the zero box jsdom really gives every element, once, on observe.
 */
class StubResizeObserver implements ResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}

  observe(target: Element): void {
    const entry = { target, contentRect: target.getBoundingClientRect() } as ResizeObserverEntry;
    this.callback([entry], this);
  }

  unobserve(): void {}

  disconnect(): void {}
}

// TypeScript declares ResizeObserver as always present; in jsdom it is not.
if (!("ResizeObserver" in globalThis)) globalThis.ResizeObserver = StubResizeObserver;
