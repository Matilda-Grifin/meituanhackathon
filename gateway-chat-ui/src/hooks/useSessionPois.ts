import { useEffect, useState } from "react";
import { clientContextApiBase } from "../location";
import type { SessionPoi } from "../types/sessionPoi";

export function useSessionPois(sessionKey: string, refreshKey: number): SessionPoi[] {
  const [pois, setPois] = useState<SessionPoi[]>([]);

  useEffect(() => {
    const sk = sessionKey.trim();
    if (!sk) {
      setPois([]);
      return;
    }
    const base = clientContextApiBase();
    const url = `${base}/api/session-pois?session_key=${encodeURIComponent(sk)}`;
    let cancelled = false;
    void fetch(url)
      .then((r) => r.json())
      .then((d: { ok?: boolean; pois?: SessionPoi[] }) => {
        if (!cancelled && d.ok && Array.isArray(d.pois)) setPois(d.pois);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [sessionKey, refreshKey]);

  return pois;
}
