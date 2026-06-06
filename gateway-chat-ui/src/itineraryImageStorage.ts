/** 行程一览图气泡：按 sessionKey 本地持久化（网关 history 不含生图行） */

import type { ChatRow } from "./chatHistoryMerge";
import { findLongestPlanText, rowsHasItineraryImage } from "./itineraryImage";
import { isItineraryImageBubble } from "./presentChatRows";

const LS_KEY = "gw.chat.itineraryImages";

type StoredItineraryImage = {
  planFp: string;
  row: ChatRow;
  updatedAt: number;
};

function readStore(): Record<string, StoredItineraryImage> {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return {};
    const j = JSON.parse(raw) as unknown;
    if (!j || typeof j !== "object") return {};
    return j as Record<string, StoredItineraryImage>;
  } catch {
    return {};
  }
}

function writeStore(store: Record<string, StoredItineraryImage>): void {
  try {
    const keys = Object.keys(store).sort((a, b) => (store[b]?.updatedAt ?? 0) - (store[a]?.updatedAt ?? 0));
    const trimmed: Record<string, StoredItineraryImage> = {};
    for (const k of keys.slice(0, 80)) {
      const v = store[k];
      if (v?.row?.text && v.planFp) trimmed[k] = v;
    }
    localStorage.setItem(LS_KEY, JSON.stringify(trimmed));
  } catch {
    // ignore quota / private mode
  }
}

export function persistItineraryImageRow(sessionKey: string, planFp: string, row: ChatRow): void {
  const sk = sessionKey.trim();
  if (!sk || !planFp || !row.text.trim()) return;
  const store = readStore();
  store[sk] = { planFp, row, updatedAt: Date.now() };
  writeStore(store);
}

export function loadPersistedItineraryImageForSession(sessionKey: string): ChatRow | null {
  const sk = sessionKey.trim();
  if (!sk) return null;
  return readStore()[sk]?.row ?? null;
}

export function sessionHasPersistedItineraryImage(sessionKey: string): boolean {
  return Boolean(loadPersistedItineraryImageForSession(sessionKey));
}

function insertImageRowAfterPlan(rows: ChatRow[], imgRow: ChatRow): ChatRow[] {
  let bestIdx = -1;
  let bestLen = 0;
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i]!;
    if (String(r.role).toLowerCase() !== "assistant") continue;
    if (isItineraryImageBubble(r.text)) continue;
    if (r.text.length > bestLen) {
      bestLen = r.text.length;
      bestIdx = i;
    }
  }
  if (bestIdx < 0) return [...rows, imgRow];
  const next = [...rows];
  next.splice(bestIdx + 1, 0, imgRow);
  return next;
}

/** history 合并后：若服务端无图且本地有缓存，补回气泡（多轮追问时方案指纹可能微变，按 session 恢复） */
export function appendPersistedItineraryImage(sessionKey: string, rows: ChatRow[]): ChatRow[] {
  if (!sessionKey.trim() || rowsHasItineraryImage(rows)) return rows;
  if (!findLongestPlanText(rows)) return rows;
  const stored = loadPersistedItineraryImageForSession(sessionKey);
  if (!stored) return rows;
  return insertImageRowAfterPlan(rows, stored);
}

export function clearPersistedItineraryImage(sessionKey: string): void {
  const sk = sessionKey.trim();
  if (!sk) return;
  const store = readStore();
  if (!store[sk]) return;
  delete store[sk];
  writeStore(store);
}
