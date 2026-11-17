import { useRef } from "react";

/** Drag and keyboard resizing shared by the left and right panels. */
export function PanelResizeHandle({
  edge,
  label,
  width,
  min,
  max,
  step,
  onResize,
}: {
  edge: "left" | "right";
  label: string;
  width: number;
  min: number;
  max: number;
  step: number;
  onResize: (width: number) => void;
}) {
  const drag = useRef<{ x: number; width: number } | null>(null);
  const direction = edge === "right" ? 1 : -1;
  return (
    <div
      role="separator"
      tabIndex={0}
      aria-label={label}
      aria-orientation="vertical"
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={width}
      className={`absolute inset-y-0 z-30 hidden w-2 cursor-col-resize touch-none select-none hover:bg-primary/15 focus-visible:bg-primary/15 focus-visible:outline-none md:block ${edge === "left" ? "left-0 -translate-x-1/2" : "right-0 translate-x-1/2"}`}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.currentTarget.focus();
        drag.current = { x: event.clientX, width };
        event.currentTarget.setPointerCapture(event.pointerId);
        event.preventDefault();
      }}
      onPointerMove={(event) => {
        if (drag.current)
          onResize(
            drag.current.width + direction * (event.clientX - drag.current.x),
          );
      }}
      onPointerUp={(event) => {
        drag.current = null;
        if (event.currentTarget.hasPointerCapture(event.pointerId))
          event.currentTarget.releasePointerCapture(event.pointerId);
      }}
      onPointerCancel={() => {
        drag.current = null;
      }}
      onLostPointerCapture={() => {
        drag.current = null;
      }}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          onResize(
            width + direction * (event.key === "ArrowRight" ? step : -step),
          );
        }
      }}
    />
  );
}
