import type { SessionPoi } from "./types/sessionPoi";

export type PlanSegment =
  | { kind: "text"; text: string }
  | { kind: "poi"; poi: SessionPoi };

const DAILY_SECTION_MARKERS: RegExp[] = [
  /\n#{1,3}\s*每天怎么玩/,
  /每天怎么玩[：:]/,
  /\n#{1,3}\s*每日行程/,
  /\n#{1,3}\s*详细安排/,
  /\n#{1,3}\s*分时段/,
  /\nDay\s*1[：:\s（(]/i,
  /\n第\s*1\s*天/,
  /\n#{1,3}\s*上午[：:]/,
  /\n#{1,3}\s*傍晚[：:]/,
  /\n#{1,3}\s*下午[：:]/,
];

const IMAGE_LINE_RE = /^!\[[^\]]*\]\([^)]+\)$/;
const AMAP_HOST = String.raw`(?:uri\.)?amap\.com`;
const AMAP_PLACE_URL = String.raw`https?:\/\/${AMAP_HOST}\/place\/[^)\s]+`;

/** 整行：任意 alt 的高德 place 链接（含 `[](url)`） */
const AMAP_MD_LINK_LINE_RE = new RegExp(String.raw`^\[[^\]]*\]\(\s*${AMAP_PLACE_URL}\s*\)$`, "i");
/** 残缺 markdown：`](url)` 或 `(url)` 单独成行 */
const AMAP_ORPHAN_TAIL_LINE_RE = new RegExp(String.raw`^\]\(\s*${AMAP_PLACE_URL}\s*\)$`, "i");
const AMAP_BARE_PAREN_LINE_RE = new RegExp(String.raw`^\(\s*${AMAP_PLACE_URL}\s*\)$`, "i");
const AMAP_BARE_URL_LINE_RE = new RegExp(String.raw`^${AMAP_PLACE_URL}\s*$`, "i");

function isAmapArtifactLine(trimmed: string): boolean {
  if (!trimmed) return false;
  if (trimmed === "]" || trimmed === "(") return true;
  if (IMAGE_LINE_RE.test(trimmed)) return true;
  if (AMAP_MD_LINK_LINE_RE.test(trimmed)) return true;
  if (AMAP_ORPHAN_TAIL_LINE_RE.test(trimmed)) return true;
  if (AMAP_BARE_PAREN_LINE_RE.test(trimmed)) return true;
  if (AMAP_BARE_URL_LINE_RE.test(trimmed)) return true;
  if (trimmed.length < 120 && /高德|amap\.com|查看详情|uri\.amap/i.test(trimmed)) return true;
  return false;
}

/** 行内 / 跨行残留的高德 place 链（地点栏已展示时去掉） */
function stripAmapPlaceArtifacts(text: string, poiIds: string[]): string {
  let out = text;
  const placeUrl = String.raw`https?:\/\/(?:uri\.)?amap\.com\/place\/[^)\s]+`;

  out = out.replace(new RegExp(String.raw`\s*!\[[^\]]*\]\([^)]+\)`, "g"), "");
  out = out.replace(new RegExp(String.raw`\s*\[[^\]]*\]\(\s*${placeUrl}\s*\)`, "gi"), "");
  out = out.replace(new RegExp(String.raw`\s*\]\(\s*${placeUrl}\s*\)`, "gi"), "");
  out = out.replace(new RegExp(String.raw`\s*\(\s*${placeUrl}\s*\)`, "gi"), "");
  out = out.replace(new RegExp(String.raw`^\s*${placeUrl}\s*$`, "gim"), "");

  for (const id of poiIds) {
    const eid = escapeRegExp(id.trim());
    if (!eid) continue;
    const idUrl = String.raw`https?:\/\/(?:uri\.)?amap\.com\/place\/${eid}[^)\s]*`;
    out = out.replace(new RegExp(String.raw`\s*\[[^\]]*\]\(\s*${idUrl}\s*\)`, "gi"), "");
    out = out.replace(new RegExp(String.raw`\s*\]\(\s*${idUrl}\s*\)`, "gi"), "");
    out = out.replace(new RegExp(String.raw`\s*\(\s*${idUrl}\s*\)`, "gi"), "");
  }

  out = out.replace(/^\s*[\]\(]\s*$/gm, "");
  out = cleanOrphanLinkBracket(out);
  return out;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 地点栏已展示后，去掉正文中重复的配图 + 高德链接（与卡片内容重复） */
export function stripDuplicatePoiMedia(text: string, embeddedPois: SessionPoi[]): string {
  if (!embeddedPois.length || !text.trim()) return text;
  let out = text;
  const poiIds = embeddedPois.map((p) => p.id);

  for (const poi of embeddedPois) {
    const n = escapeRegExp(poi.name.trim());
    if (!n) continue;

    out = out.replace(
      new RegExp(
        String.raw`\n{0,2}!\[[^\]]*\]\([^)]+\)\s*\n{0,2}\[[^\]]*${n}[^\]]*\]\([^)]*(?:amap\.com|uri\.amap)[^)]*\)`,
        "gi",
      ),
      "\n",
    );
    out = out.replace(
      new RegExp(
        String.raw`\n{0,2}\[[^\]]*${n}[^\]]*\]\([^)]*(?:amap\.com|uri\.amap)[^)]*\)\s*`,
        "gi",
      ),
      "\n",
    );
    out = out.replace(
      /\n{0,2}!\[[^\]]*\]\([^)]+\)\s*\n{0,2}\[[^\]]*\]\([^)]*(?:amap\.com|uri\.amap)[^)]*\)/gi,
      "\n",
    );
  }

  out = out.replace(/\n{2,}!\[[^\]]*\]\(https?:\/\/[^)]+\)\s*(?=\n+(?:推荐|[-*•]|#{1,3}|\d|[^\n![]))/g, "\n\n");
  out = stripAmapPlaceArtifacts(out, poiIds);

  return out.replace(/\n{3,}/g, "\n\n").trim();
}

/** 每日行程区起点：行程速览表之后，或「每天怎么玩 / 详细安排」等标题 */
export function findDailySectionStart(planText: string): number {
  let best = -1;
  for (const re of DAILY_SECTION_MARKERS) {
    const m = re.exec(planText);
    if (m && (best < 0 || m.index < best)) best = m.index;
  }
  if (best >= 0) return best;

  const overview = /(?:^|\n)(?:#{1,3}\s*)?(?:📋\s*)?行程速览/m.exec(planText);
  if (!overview) return planText.length;

  const from = overview.index + overview[0].length;
  const tail = planText.slice(from);
  const tableEnd = skipMarkdownTable(tail);
  return from + tableEnd;
}

function skipMarkdownTable(s: string): number {
  const lines = s.split("\n");
  let i = 0;
  while (i < lines.length && !lines[i]!.includes("|")) i++;
  if (i >= lines.length) return 0;
  while (i < lines.length && lines[i]!.includes("|")) i++;
  while (i < lines.length && !lines[i]!.trim()) i++;
  return lines.slice(0, i).join("\n").length;
}

function poiEmbedStart(text: string, nameIndex: number): number {
  let i = nameIndex - 1;
  while (i >= 0 && /\s/.test(text[i]!)) i--;
  if (i >= 0 && text[i] === "[") return i;
  return nameIndex;
}

function cleanOrphanLinkBracket(text: string): string {
  return text
    .replace(/([：:])\s*\[\s*$/gm, "$1 ")
    .replace(/\[\s*$/gm, "")
    .replace(/^\s*\]\s*$/gm, "");
}

function poiInText(poi: SessionPoi, text: string): boolean {
  const name = poi.name.trim();
  return name.length >= 2 && text.includes(name);
}

/** 从 POI 名称位置向后吞掉配图、高德链接行（替换为地点栏） */
export function consumePoiMediaAfter(text: string, nameIndex: number, name: string): number {
  let end = nameIndex + name.length;

  const inlineTail = text.slice(end).match(
    new RegExp(String.raw`^[）)]?\s*（?\s*\[[^\]]*\]\(\s*${AMAP_PLACE_URL}\s*\)\s*）?`),
  );
  if (inlineTail) end += inlineTail[0].length;

  const orphanClose = text.slice(end).match(
    new RegExp(String.raw`^\]\(\s*${AMAP_PLACE_URL}\s*\)`),
  );
  if (orphanClose) end += orphanClose[0].length;

  while (end < text.length) {
    const rest = text.slice(end);
    if (rest.startsWith("\r\n")) {
      end += 2;
      continue;
    }
    if (rest.startsWith("\n")) {
      const lineEnd = rest.indexOf("\n", 1);
      const line = lineEnd === -1 ? rest.slice(1) : rest.slice(1, lineEnd);
      const trimmed = line.trim();
      if (!trimmed) {
        end += 1;
        continue;
      }
      if (isAmapArtifactLine(trimmed)) {
        end += lineEnd === -1 ? rest.length : lineEnd + 1;
        continue;
      }
      break;
    }
    break;
  }

  return end;
}

function splitDailyWithPois(dailyText: string, pois: SessionPoi[]): PlanSegment[] {
  const matched = pois.filter((p) => poiInText(p, dailyText));
  if (!matched.length) return [{ kind: "text", text: dailyText }];

  const byFirstPos = [...matched].sort((a, b) => {
    const ia = dailyText.indexOf(a.name);
    const ib = dailyText.indexOf(b.name);
    return ia - ib || b.name.length - a.name.length;
  });

  const segments: PlanSegment[] = [];
  let cursor = 0;
  const usedIds = new Set<string>();

  for (const poi of byFirstPos) {
    const idx = dailyText.indexOf(poi.name, cursor);
    if (idx < 0) continue;
    if (usedIds.has(poi.id)) continue;

    const embedStart = poiEmbedStart(dailyText, idx);
    const blockEnd = consumePoiMediaAfter(dailyText, idx, poi.name);
    if (embedStart > cursor) {
      segments.push({
        kind: "text",
        text: cleanOrphanLinkBracket(dailyText.slice(cursor, embedStart)),
      });
    }
    segments.push({ kind: "poi", poi });
    cursor = blockEnd;
    usedIds.add(poi.id);
  }

  if (cursor < dailyText.length) {
    segments.push({ kind: "text", text: dailyText.slice(cursor) });
  }

  const embedded = segments.filter((s): s is { kind: "poi"; poi: SessionPoi } => s.kind === "poi");
  const allEmbedded = embedded.map((e) => e.poi);
  const cleaned = segments.map((seg) => {
    if (seg.kind !== "text") return seg;
    const text = stripDuplicatePoiMedia(seg.text, allEmbedded);
    return text.trim() ? { kind: "text" as const, text } : null;
  }).filter((s): s is { kind: "text"; text: string } => s != null);
  return cleaned.length ? cleaned : [{ kind: "text", text: dailyText }];
}

/** 行程速览区纯文本；每日行程区内嵌地点栏并替换配图/链接 */
export function splitPlanWithPois(planText: string, pois: SessionPoi[]): PlanSegment[] {
  const dailyStart = findDailySectionStart(planText);
  const segments: PlanSegment[] = [];

  if (dailyStart > 0) {
    segments.push({ kind: "text", text: planText.slice(0, dailyStart) });
  } else if (dailyStart === planText.length) {
    return [{ kind: "text", text: planText }];
  }

  const dailyText = planText.slice(dailyStart);
  segments.push(...splitDailyWithPois(dailyText, pois));
  return segments;
}
