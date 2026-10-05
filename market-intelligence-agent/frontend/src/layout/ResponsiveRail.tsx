import { useEffect, useId, useRef, type PropsWithChildren, type ReactElement, type RefObject } from "react";
import { Icon } from "../ui/Icon";

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export function useDialogFocus({
  open,
  onClose,
  openerRef,
  containerRef,
  initialFocusRef,
}: {
  open: boolean;
  onClose: () => void;
  openerRef: RefObject<HTMLButtonElement | null>;
  containerRef: RefObject<HTMLElement | null>;
  initialFocusRef: RefObject<HTMLButtonElement | null>;
}) {
  useEffect(() => {
    if (!open) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    initialFocusRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = Array.from(
        containerRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR) ?? [],
      );
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      openerRef.current?.focus();
    };
  }, [containerRef, initialFocusRef, onClose, open, openerRef]);
}

export function ResponsiveRail({
  open,
  side,
  title,
  onClose,
  openerRef,
  className = "",
  children,
}: PropsWithChildren<{
  open: boolean;
  side: "left" | "right";
  title: string;
  onClose: () => void;
  openerRef: RefObject<HTMLButtonElement | null>;
  className?: string;
}>): ReactElement {
  const railRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  useDialogFocus({ open, onClose, openerRef, containerRef: railRef, initialFocusRef: closeRef });

  const edgeClass = side === "left" ? "left-0 border-r" : "right-0 border-l";
  const openClass = open ? "translate-x-0" : side === "left" ? "-translate-x-full" : "translate-x-full";
  const visibilityClass = open ? "visible" : "invisible xl:visible";
  const overlayId = `${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-overlay`;

  return (
    <>
      {open && (
        <div
          data-testid={overlayId}
          className="fixed inset-0 z-40 bg-slate-950/35 backdrop-blur-[1px] xl:hidden"
          aria-hidden="true"
          onClick={onClose}
        />
      )}
      <aside
        ref={railRef}
        role={open ? "dialog" : undefined}
        aria-modal={open ? "true" : undefined}
        aria-labelledby={open ? titleId : undefined}
        className={`fixed inset-y-0 z-50 flex w-72 flex-col border-terminal-border bg-surface-elevated shadow-2xl transition-transform duration-200 xl:static xl:z-auto xl:translate-x-0 xl:shadow-none ${edgeClass} ${openClass} ${visibilityClass} ${className}`}
      >
        <div className="flex items-center justify-between border-b border-terminal-border px-4 py-3 xl:hidden">
          <h2 id={titleId} className="text-sm font-semibold text-terminal-text">{title}</h2>
          <button
            ref={closeRef}
            type="button"
            aria-label={`Close ${title}`}
            onClick={onClose}
            className="grid h-9 w-9 place-items-center rounded-lg text-terminal-muted transition-colors hover:bg-surface-soft hover:text-terminal-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue"
          >
            <Icon name="close" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </aside>
    </>
  );
}
