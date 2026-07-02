import { useEffect, useRef, useState } from "react";
import { useStreamReveal } from "../hooks/useStreamReveal";

type ThinkingBubbleProps = {
  main: string;
  sub?: string;
  /** false 时播放收起动画后卸载 */
  visible: boolean;
};

const COLLAPSE_MS = 340;

export function ThinkingBubble({ main, sub, visible }: ThinkingBubbleProps) {
  const [mounted, setMounted] = useState(visible);
  const [collapsing, setCollapsing] = useState(false);
  const collapseTimer = useRef<number | null>(null);

  useEffect(() => {
    if (visible) {
      if (collapseTimer.current != null) {
        window.clearTimeout(collapseTimer.current);
        collapseTimer.current = null;
      }
      setCollapsing(false);
      setMounted(true);
      return;
    }
    if (!mounted) return;
    setCollapsing(true);
    collapseTimer.current = window.setTimeout(() => {
      setMounted(false);
      setCollapsing(false);
      collapseTimer.current = null;
    }, COLLAPSE_MS);
    return () => {
      if (collapseTimer.current != null) {
        window.clearTimeout(collapseTimer.current);
      }
    };
  }, [visible, mounted]);

  const streamMain = useStreamReveal(main, mounted && visible && !collapsing);
  const streamSub = useStreamReveal(sub ?? "", mounted && visible && !collapsing && !!sub);

  if (!mounted) return null;

  return (
    <div
      className={`thinking-in-stream${collapsing ? " thinking-in-stream--collapse" : ""}`}
      aria-live="polite"
      aria-hidden={collapsing}
    >
      <div className="thinking-bubble-inner">
          <span className="thinking-dot" aria-hidden />
          <div className="thinking-text">
            <p className="thinking-main">
              {streamMain}
              {streamMain.length < main.length ? <span className="thinking-caret" /> : null}
            </p>
            {sub && streamSub ? <p className="thinking-sub">{streamSub}</p> : null}
          </div>
        </div>
    </div>
  );
}
