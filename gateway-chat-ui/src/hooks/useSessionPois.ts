import { useEffect, useState } from "react";
import { clientContextApiBase } from "../location";
import type { SessionPoi } from "../types/sessionPoi";

function poisSignature(pois: SessionPoi[]): string {
  return pois
    .map((p) => {
      const loc = p.location;
      return `${p.id}:${loc?.lng ?? ""},${loc?.lat ?? ""}`;
    })
    .join("|");
}

export function useSessionPois(sessionKey: string, refreshKey: string | number): SessionPoi[] {
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
        if (!cancelled && d.ok && Array.isArray(d.pois)) {
          const next = d.pois;
          setPois((prev) => (poisSignature(prev) === poisSignature(next) ? prev : next));
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [sessionKey, refreshKey]);

  return pois;
}
