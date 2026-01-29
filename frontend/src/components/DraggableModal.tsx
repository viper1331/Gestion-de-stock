import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface DraggableModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  maxWidthClassName?: string;
  bodyClassName?: string;
}

const MODAL_PADDING = 16;

export function DraggableModal({
  open,
  title,
  onClose,
  children,
  footer,
  maxWidthClassName = "max-w-3xl",
  bodyClassName = "px-4 py-4"
}: DraggableModalProps) {
  const modalRef = useRef<HTMLDivElement | null>(null);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragOffset = useRef({ x: 0, y: 0 });

  const clampPosition = useMemo(() => {
    return (x: number, y: number) => {
      const maxX = Math.max(MODAL_PADDING, window.innerWidth - dimensions.width - MODAL_PADDING);
      const maxY = Math.max(MODAL_PADDING, window.innerHeight - dimensions.height - MODAL_PADDING);
      return {
        x: Math.min(Math.max(MODAL_PADDING, x), maxX),
        y: Math.min(Math.max(MODAL_PADDING, y), maxY)
      };
    };
  }, [dimensions.height, dimensions.width]);

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
    const resizeHandler = () => {
      setPosition((prev) => clampPosition(prev.x, prev.y));
    };
    window.addEventListener("resize", resizeHandler);
    return () => window.removeEventListener("resize", resizeHandler);
  }, [clampPosition, open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const raf = window.requestAnimationFrame(() => {
      if (!modalRef.current) {
        return;
      }
      const rect = modalRef.current.getBoundingClientRect();
      setDimensions({ width: rect.width, height: rect.height });
      setPosition(
        clampPosition(
          window.innerWidth / 2 - rect.width / 2,
          window.innerHeight / 2 - rect.height / 2
        )
      );
    });
    return () => window.cancelAnimationFrame(raf);
  }, [clampPosition, open]);

  useEffect(() => {
    if (!isDragging) {
      return;
    }
    const handleMouseMove = (event: MouseEvent) => {
      const nextX = event.clientX - dragOffset.current.x;
      const nextY = event.clientY - dragOffset.current.y;
      setPosition(clampPosition(nextX, nextY));
    };
    const handleMouseUp = () => {
      setIsDragging(false);
    };
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [clampPosition, isDragging]);

  if (!open) {
    return null;
  }

  const content = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-x-hidden bg-slate-950/80 px-4"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        ref={modalRef}
        className={`absolute flex w-full min-w-0 max-h-[90vh] ${maxWidthClassName} flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 shadow-2xl`}
        style={{ left: position.x, top: position.y }}
      >
        <div
          className="flex min-w-0 shrink-0 cursor-move items-center justify-between border-b border-slate-800 px-4 py-3"
          onMouseDown={(event) => {
            event.preventDefault();
            if (!modalRef.current) {
              return;
            }
            const rect = modalRef.current.getBoundingClientRect();
            dragOffset.current = {
              x: event.clientX - rect.left,
              y: event.clientY - rect.top
            };
            setIsDragging(true);
          }}
        >
          <h4 className="text-sm font-semibold text-white">{title}</h4>
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-slate-400 hover:text-slate-200"
          >
            ✕
          </button>
        </div>
        <div className={`min-w-0 flex-1 overflow-y-auto overflow-x-hidden ${bodyClassName}`}>
          {children}
        </div>
        {footer ? (
          <div className="shrink-0 border-t border-slate-800 bg-slate-900 px-4 py-3">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );

  if (typeof document === "undefined" || !document.body) {
    return content;
  }

  return createPortal(content, document.body);
}
