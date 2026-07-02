import { useEffect, useState } from "react";

/** 逐字露出文案，用于底部进度气泡 */
export function useStreamReveal(text: string, active: boolean, stepMs = 38): string {
  const [len, setLen] = useState(0);

  useEffect(() => {
    if (!active || !text) {
      setLen(0);
      return;
    }
    setLen(0);
    const tick = Math.max(1, Math.ceil(text.length / 48));
    const id = window.setInterval(() => {
      setLen((n) => {
        if (n >= text.length) {
          window.clearInterval(id);
          return n;
        }
        return Math.min(text.length, n + tick);
      });
    }, stepMs);
    return () => window.clearInterval(id);
  }, [text, active, stepMs]);

  if (!active || !text) return "";
  return text.slice(0, len);
}
