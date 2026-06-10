import "@testing-library/jest-dom/vitest";

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
