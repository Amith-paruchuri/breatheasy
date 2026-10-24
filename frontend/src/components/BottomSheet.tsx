import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

export type Snap = "peek" | "half" | "full";

interface Props {
  snap: Snap;
  onSnap: (s: Snap) => void;
  children: ReactNode;
  label: string;
}

/** Visible height for each snap point, in px. */
export function heights(): Record<Snap, number> {
  const vh = window.innerHeight;
  // "full" leaves the brand bar and account button visible above the sheet.
  return { peek: 148, half: Math.round(vh * 0.55), full: vh - 64 };
}

/**
 * Mobile bottom sheet with three snap points. Drag the grab bar (or tap it to
 * cycle). Content scrolls inside; dragging only starts from the header area so
 * scrolling a list never fights the sheet.
 */
export function BottomSheet({ snap, onSnap, children, label }: Props) {
  const [drag, setDrag] = useState<number | null>(null); // visible height while dragging
  const start = useRef<{ y: number; h: number; t: number } | null>(null);
  const [, force] = useState(0);

  useEffect(() => {
    const r = () => force((n) => n + 1);
    window.addEventListener("resize", r);
    return () => window.removeEventListener("resize", r);
  }, []);

  const H = heights();
  const visible = drag ?? H[snap];

  const onDown = useCallback(
    (e: React.PointerEvent) => {
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      start.current = { y: e.clientY, h: heights()[snap], t: performance.now() };
    },
    [snap],
  );

  const onMove = useCallback((e: React.PointerEvent) => {
    if (!start.current) return;
    const h = heights();
    const next = Math.min(h.full, Math.max(h.peek - 40, start.current.h + (start.current.y - e.clientY)));
    if (Math.abs(start.current.y - e.clientY) > 4) setDrag(next);
  }, []);

  const onUp = useCallback(
    (e: React.PointerEvent) => {
      const s = start.current;
      start.current = null;
      if (!s) return;
      const moved = s.y - e.clientY;
      if (Math.abs(moved) <= 4) {
        // a tap on the grab area cycles peek -> half -> full -> half
        onSnap(snap === "peek" ? "half" : snap === "half" ? "full" : "half");
        setDrag(null);
        return;
      }
      const h = heights();
      const v = moved / Math.max(1, performance.now() - s.t); // px per ms, + is up
      const cur = s.h + moved;
      let target: Snap;
      if (v > 0.6) target = snap === "peek" ? "half" : "full";
      else if (v < -0.6) target = snap === "full" ? "half" : "peek";
      else
        target = (Object.keys(h) as Snap[]).reduce((best, k) => (Math.abs(h[k] - cur) < Math.abs(h[best] - cur) ? k : best), "half");
      setDrag(null);
      onSnap(target);
    },
    [snap, onSnap],
  );

  return (
    <section
      className={`bsheet${drag !== null ? " dragging" : ""}`}
      style={{ transform: `translateY(calc(100% - ${visible}px))` }}
      aria-label={label}
      data-snap={snap}
    >
      <div
        className="bsheet-grab"
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={() => {
          start.current = null;
          setDrag(null);
        }}
        role="button"
        tabIndex={0}
        aria-label={snap === "full" ? "Collapse results" : "Expand results"}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") onSnap(snap === "full" ? "half" : "full");
          if (e.key === "ArrowUp") onSnap(snap === "peek" ? "half" : "full");
          if (e.key === "ArrowDown") onSnap(snap === "full" ? "half" : "peek");
        }}
      >
        <span />
      </div>
      <div className="bsheet-body" style={{ maxHeight: `${visible - 22}px` }}>
        {children}
      </div>
    </section>
  );
}
