import "@testing-library/jest-dom/vitest";

// jsdom has no Element.prototype.scrollIntoView; cmdk (the R0 CommandPalette)
// calls it on the selected item. Guarded no-op — steps aside if jsdom ships it.
if (
  typeof Element !== "undefined" &&
  typeof Element.prototype.scrollIntoView !== "function"
) {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}

// jsdom has no ResizeObserver; cmdk observes its list for height animation.
// Guarded inert stub — observations never fire, which cmdk tolerates.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// jsdom has no IntersectionObserver; the R2 dossier stepper observes its
// journey sections for scrollspy. Guarded stub that RECORDS its instances on
// globalThis.__IO_INSTANCES__ so a test can drive the callback DELIBERATELY —
// nothing ever fires on its own, so every other suite sees an inert observer.
if (typeof globalThis.IntersectionObserver === "undefined") {
  const instances: unknown[] = [];
  class StubIntersectionObserver {
    callback: IntersectionObserverCallback;
    elements = new Set<Element>();
    root = null;
    rootMargin = "";
    thresholds: number[] = [];
    constructor(cb: IntersectionObserverCallback) {
      this.callback = cb;
      instances.push(this);
    }
    observe(el: Element) {
      this.elements.add(el);
    }
    unobserve(el: Element) {
      this.elements.delete(el);
    }
    disconnect() {
      this.elements.clear();
      const i = instances.indexOf(this);
      if (i >= 0) instances.splice(i, 1);
    }
    takeRecords(): IntersectionObserverEntry[] {
      return [];
    }
  }
  globalThis.IntersectionObserver =
    StubIntersectionObserver as unknown as typeof IntersectionObserver;
  (globalThis as unknown as Record<string, unknown>).__IO_INSTANCES__ =
    instances;
}

// jsdom (29.x) declares HTMLDialogElement but does not implement
// showModal()/close() — calling them throws "is not a function". The
// IterationDetailModal rides the NATIVE <dialog> element (no new deps), so
// give jsdom the minimal behavior the component contract needs:
//   - showModal() opens the dialog (the `open` attribute, like the platform);
//   - close(returnValue?) clears `open` and fires a `close` Event — React's
//     onClose (and therefore the modal's focus-restore path) hangs off that
//     event exactly as in a real browser.
// Guarded assignments only: if a future jsdom ships the real implementation,
// the polyfill steps aside.
if (typeof HTMLDialogElement !== "undefined") {
  const proto = HTMLDialogElement.prototype as HTMLDialogElement & {
    showModal?: () => void;
    show?: () => void;
    close?: (returnValue?: string) => void;
  };
  if (typeof proto.showModal !== "function") {
    proto.showModal = function showModal(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    };
  }
  if (typeof proto.show !== "function") {
    proto.show = function show(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    };
  }
  if (typeof proto.close !== "function") {
    proto.close = function close(
      this: HTMLDialogElement,
      returnValue?: string,
    ) {
      if (!this.hasAttribute("open")) return;
      this.removeAttribute("open");
      if (returnValue !== undefined) this.returnValue = returnValue;
      this.dispatchEvent(new Event("close"));
    };
  }
}
