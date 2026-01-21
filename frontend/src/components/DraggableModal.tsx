import { ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface DraggableModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  disableDragOnMobile?: boolean;
  initialX?: number;
  initialY?: number;
  width?: number | string;
  maxHeight?: number | string;
}

type DragState = {
  startX: number;
  startY: number;
  originX: number;
  originY: number;
};

const DEFAULT_MODAL_WIDTH = "min(900px, 92vw)";
const DEFAULT_MODAL_MAX_HEIGHT = "85vh";
const MIN_VISIBLE_EDGE = 48;
const MIN_VISIBLE_TITLEBAR = 56;

const clampValue = (value: number, min: number, max: number) => Math.max(min, Math.min(value, max));

export function DraggableModal({
  open,
  title,
  onClose,
  children,
  footer,
  disableDragOnMobile = true,
  initialX,
  initialY,
  width,
  maxHeight
}: DraggableModalProps) {
  const titleId = useId();
  const modalRef = useRef<HTMLDivElement>(null);
  const titleBarRef = useRef<HTMLDivElement>(null);
  const dragState = useRef<DragState | null>(null);
  const [position, setPosition] = useState({ x: initialX ?? 0, y: initialY ?? 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [isMobile, setIsMobile] = useState(false);

  const resolveWidth = width ?? DEFAULT_MODAL_WIDTH;
  const resolveMaxHeight = maxHeight ?? DEFAULT_MODAL_MAX_HEIGHT;

  const clampPosition = useCallback(
    (nextX: number, nextY: number) => {
      const modal = modalRef.current;
      if (!modal) {
        return { x: nextX, y: nextY };
      }
      const rect = modal.getBoundingClientRect();
      const titleHeight = titleBarRef.current?.getBoundingClientRect().height ?? MIN_VISIBLE_TITLEBAR;
      const minTitlebarVisible = Math.max(titleHeight, MIN_VISIBLE_TITLEBAR);
      const minX = -(rect.width - MIN_VISIBLE_EDGE);
      const maxX = window.innerWidth - MIN_VISIBLE_EDGE;
      const minY = -(rect.height - minTitlebarVisible);
      const maxY = window.innerHeight - minTitlebarVisible;
      return {
        x: clampValue(nextX, minX, maxX),
        y: clampValue(nextY, minY, maxY)
      };
    },
    []
  );

  const centerModal = useCallback(() => {
    const modal = modalRef.current;
    if (!modal) {
      return;
    }
    const rect = modal.getBoundingClientRect();
    const nextX = initialX ?? (window.innerWidth - rect.width) / 2;
    const nextY = initialY ?? (window.innerHeight - rect.height) / 2;
    setPosition(clampPosition(nextX, nextY));
  }, [clampPosition, initialX, initialY]);

  useEffect(() => {
    if (!disableDragOnMobile) {
      setIsMobile(false);
      return;
    }
    const media = window.matchMedia("(max-width: 640px)");
    const updateMobile = () => setIsMobile(media.matches);
    updateMobile();
    media.addEventListener("change", updateMobile);
    return () => media.removeEventListener("change", updateMobile);
  }, [disableDragOnMobile]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    if (isMobile) {
      setPosition({ x: 0, y: 0 });
      return;
    }
    requestAnimationFrame(() => {
      centerModal();
      modalRef.current?.focus();
    });
  }, [centerModal, isMobile, open]);

  useEffect(() => {
    if (!open || isMobile) {
      return;
    }
    const handleResize = () => {
      setPosition((current) => clampPosition(current.x, current.y));
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [clampPosition, isMobile, open]);

  useEffect(() => {
    if (!open || isMobile) {
      return;
    }
    const modal = modalRef.current;
    if (!modal || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(() => {
      setPosition((current) => clampPosition(current.x, current.y));
    });
    observer.observe(modal);
    return () => observer.disconnect();
  }, [clampPosition, isMobile, open]);

  useEffect(() => {
    if (!isDragging) {
      return;
    }

    const handlePointerMove = (event: PointerEvent) => {
      if (!dragState.current) {
        return;
      }
      const nextX = dragState.current.originX + (event.clientX - dragState.current.startX);
      const nextY = dragState.current.originY + (event.clientY - dragState.current.startY);
      setPosition(clampPosition(nextX, nextY));
    };

    const endDrag = () => {
      dragState.current = null;
      setIsDragging(false);
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", endDrag);
    window.addEventListener("pointercancel", endDrag);

    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", endDrag);
      window.removeEventListener("pointercancel", endDrag);
    };
  }, [clampPosition, isDragging]);

  if (!open) {
    return null;
  }

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (isMobile) {
      return;
    }
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    dragState.current = {
      startX: event.clientX,
      startY: event.clientY,
      originX: position.x,
      originY: position.y
    };
    setIsDragging(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const modalStyle = isMobile
    ? {
        left: 0,
        top: 0,
        width: "100vw",
        height: "100vh",
        maxHeight: "100vh"
      }
    : {
        left: `${position.x}px`,
        top: `${position.y}px`,
        width: typeof resolveWidth === "number" ? `${resolveWidth}px` : resolveWidth,
        maxHeight: typeof resolveMaxHeight === "number" ? `${resolveMaxHeight}px` : resolveMaxHeight
      };

  return createPortal(
    <div className="fixed inset-0 z-40">
      <div
        className="fixed inset-0 bg-slate-950/70"
        onClick={(event) => {
          if (event.target === event.currentTarget) {
            onClose();
          }
        }}
      />
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        style={modalStyle}
        className="fixed z-50 flex flex-col overflow-hidden rounded-lg border border-slate-800 bg-slate-900 shadow-2xl outline-none"
      >
        <div
          ref={titleBarRef}
          data-testid="modal-titlebar"
          onPointerDown={handlePointerDown}
          onDoubleClick={() => {
            if (!isMobile) {
              centerModal();
            }
          }}
          className={`flex items-center justify-between border-b border-slate-800 bg-slate-950 px-4 py-3 text-sm font-semibold text-white ${
            isMobile ? "cursor-default" : "cursor-move"
          }`}
        >
          <h2 id={titleId}>{title}</h2>
          <button
            type="button"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              onClose();
            }}
            className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800"
            aria-label="Fermer"
          >
            ✕
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto px-4 py-4">{children}</div>
        {footer ? (
          <div className="sticky bottom-0 border-t border-slate-800 bg-slate-950 px-4 py-3">
            {footer}
          </div>
        ) : null}
      </div>
    </div>,
    document.body
  );
}
