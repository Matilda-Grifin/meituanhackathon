/** 完整方案判定 + 行程信息图 API（方案 v3：长文 final 后第 2 条气泡） */

import { isItineraryImageBubble, stripLeadingAckFromPlan } from "./presentChatRows";
import type { ChatRow } from "./chatHistoryMerge";

/** 长文含行程速览表时，可推断已搜点（history 回填 / 断线重连） */
export function planQualifiesForSearchInference(text: string): boolean {
  const t = text.trim();
  return (/##\s*📋|行程速览/.test(t) && t.length >= 1200) || (/行程速览/.test(t) && t.length >= 2000);
}

export function resolveHadSearchPlaces(hadSearchPlaces: boolean, planText: string): boolean {
  return hadSearchPlaces || planQualifiesForSearchInference(planText);
}

export function isCompleteItineraryPlan(text: string, hadSearchPlaces: boolean): boolean {
  const t = text.trim();
  const hadSearch = resolveHadSearchPlaces(hadSearchPlaces, t);
  if (!hadSearch || t.length < 800) return false;
  if (/^选择题答案：/.test(t) || parseIntakeQuestionCount(t) > 0) return false;
  const hasOverview = /##\s*📋|行程速览/.test(t);
  if (!hasOverview) return false;
  const hasBudget = /##\s*💰|预算参考|预算|费用参考|人均|花费/.test(t);
  return hasBudget || t.length >= 1000;
}

export function rowsHasItineraryImage(rows: ChatRow[]): boolean {
  return rows.some((r) => {
    if (String(r.role).toLowerCase() !== "assistant") return false;
    return isItineraryImageBubble(r.text);
  });
}

export function findLongestPlanText(rows: ChatRow[], ackText?: string): string {
  let best = "";
  for (const r of rows) {
    if (String(r.role).toLowerCase() !== "assistant") continue;
    const t = r.text.trim();
    if (!t || isItineraryImageBubble(t)) continue;
    if (t.length > best.length) best = t;
  }
  if (!best) return "";
  return ackText?.trim() ? stripLeadingAckFromPlan(best, ackText) : best;
}

function parseIntakeQuestionCount(text: string): number {
  const m = text.match(/第\s*1\s*题|^\s*1[\.、．]\s/m);
  if (!m) return 0;
  if (/行程速览|预算参考/.test(text)) return 0;
  return 1;
}

export function formatItineraryImageMarkdown(imageUrl: string): string {
  return `## 📸 行程一览图\n\n![行程示意图](${imageUrl})\n\n> 示意图，地点与时间以正文为准。`;
}

export function planTextFingerprint(text: string): string {
  const t = text.trim();
  const head = t.slice(0, 120);
  return `${t.length}:${head}`;
}

export type ItineraryImageResult =
  | { ok: true; image_url: string; timing_ms?: { total?: number } }
  | { ok: false; cancelled?: boolean; error?: string };

export async function requestItineraryImage(
  planMarkdown: string,
  jobId: string,
  signal: AbortSignal,
): Promise<ItineraryImageResult> {
  const res = await fetch("/api/itinerary-image", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan_markdown: planMarkdown, job_id: jobId }),
    signal,
  });
  if (!res.ok) {
    const errText = await res.text().catch(() => "");
    return { ok: false, error: errText.slice(0, 400) || `HTTP ${res.status}` };
  }
  const data = (await res.json()) as ItineraryImageResult & { cancelled?: boolean };
  if (data.cancelled) return { ok: false, cancelled: true };
  if (data.ok && typeof (data as { image_url?: string }).image_url === "string") {
    return { ok: true, image_url: (data as { image_url: string }).image_url, timing_ms: data.timing_ms };
  }
  return { ok: false, error: "empty image response" };
}

export async function cancelItineraryImageJob(jobId: string): Promise<void> {
  try {
    await fetch("/api/itinerary-image/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId }),
    });
  } catch {
    // ignore — client abort is enough for UI
  }
}

export function toolEventUsedSearchPlaces(payload: unknown): boolean {
  const raw = JSON.stringify(payload ?? "");
  return /lifecare__lifecare_search_places|lifecare_search_places/i.test(raw);
}
