// PeekPanel — the Linear-style right slide-over (R0 design system). Pure
// presentation: renders children, fetches nothing. Slides in over
// --motion-panel (250ms), focus-trapped while open, closes on Esc and on
// backdrop click, restores focus to the opener on close. Portal-rendered so
// stacking never fights route layouts.
import { ReactNode, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import "./primitives.css";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export default function PeekPanel({
  open,
  onClose,
  title,
  width = 480,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title?: string;
  /** Panel width in px (~420-520 per the design direction); capped at 92vw. */
  width?: number;
  children: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<Element | null>(null);

  // Focus management: remember the opener, move focus in, restore on close.
  useEffect(() => {
    if (!open) return;
    openerRef.current = document.activeElement;
    panelRef.current?.focus();
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
      if (openerRef.current instanceof HTMLElement) openerRef.current.focus();
    };
  }, [open]);

  // Esc closes; Tab wraps inside the panel (the trap).
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab" || !panelRef.current) return;
      const focusables = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE),
      );
      if (focusables.length === 0) {
        e.preventDefault();
        panelRef.current.focus();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || active === panelRef.current)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div data-testid="peek-root">
      <div
        className="dsn-peek-backdrop"
        data-testid="peek-backdrop"
        onClick={onClose}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title ?? "details"}
        tabIndex={-1}
        className="dsn-peek-panel"
        data-testid="peek-panel"
        style={{ "--peek-width": `${width}px` } as React.CSSProperties}
      >
        <header className="dsn-peek-head">
          <span>{title}</span>
          <button
            type="button"
            aria-label="close panel"
            onClick={onClose}
            style={{
              marginLeft: "auto",
              background: "none",
              border: "none",
              color: "var(--fg-muted)",
              cursor: "pointer",
              fontSize: "var(--text-title)",
              lineHeight: 1,
              padding: "var(--space-1)",
            }}
          >
            ×
          </button>
        </header>
        <div className="dsn-peek-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
