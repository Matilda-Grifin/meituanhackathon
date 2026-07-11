import { stripMovementDiagramSection } from "./markdownUtils";
import type { SessionPoi } from "./types/sessionPoi";

export type PlanSegment =
  | { kind: "text"; text: string }
  | { kind: "poi"; poi: SessionPoi };

const DAILY_SECTION_MARKERS: RegExp[] = [
  /\n#{1,3}\s*每天怎么玩/,
  /每天怎么玩[：:]/,
  /\n#{1,3}\s*每日行程/,
  /\n#{1,3}\s*详细安排/,
  /\n#{1,3}\s*分时段详细安排/,
  /\n#{1,3}\s*分行程详细说明/,
  /\n#{1,3}\s*分行程/,
  /\n#{1,3}\s*分时段/,
  /\nDay\s*1[：:\s（(]/i,
  /\n第\s*1\s*天/,
  /\n#{1,3}\s*上午[：:]/,
  /\n#{1,3}\s*傍晚[：:]/,
  /\n#{1,3}\s*下午[：:]/,
];

const IMAGE_LINE_RE = /^!\[[^\]]*\]\([^)]+\)$/;
/** 高德图片域名，模型输出的 POI 配图 URL */
const AUTONAVI_PHOTO_RE = /^!\[[^\]]*\]\(https?:\/\/[^)]+\)$/;
const AMAP_HOST = String.raw`(?:www\.|uri\.)?amap\.com`;
/** place id 可能含空格（模型抄写错误），匹配到 `)` 前整段 */
const AMAP_PLACE_URL = String.raw`https?:\/\/${AMAP_HOST}\/place\/[^)]+`;
const HEADING_TIME_PREFIX_RE =
  /^\d{1,2}[:：]\d{0,2}\s*[-–—~至到]+\s*\d{0,2}[:：]?\d{0,2}\s*/;

/** 整行：任意 alt 的高德 place 链接（含 `[](url)`） */
const AMAP_MD_LINK_LINE_RE = new RegExp(String.raw`^\[[^\]]*\]\(\s*${AMAP_PLACE_URL}\s*\)$`, "i");
/** 残缺 markdown：`](url)` 或 `(url)` 单独成行 */
const AMAP_ORPHAN_TAIL_LINE_RE = new RegExp(String.raw`^\]\(\s*${AMAP_PLACE_URL}\s*\)$`, "i");
const AMAP_BARE_PAREN_LINE_RE = new RegExp(String.raw`^\(\s*${AMAP_PLACE_URL}\s*\)$`, "i");
const AMAP_BARE_URL_LINE_RE = new RegExp(String.raw`^${AMAP_PLACE_URL}\s*$`, "i");

/** 对齐 lifecare.harness.poi_whitelist.normalize_poi_name */
export function normalizePoiName(name: string): string {
  let s = (name || "").trim();
  s = s.replace(/（/g, "(").replace(/）/g, ")");
  s = s.replace(/[\s·•\-—_]/g, "");
  s = s.replace(/\((总店|分店|店)\)/g, "");
  for (const suffix of [
    "店",
    "餐厅",
    "风景名胜区",
    "景区",
    "博物馆",
    "购物中心",
    "商场",
  ]) {
    if (s.endsWith(suffix) && s.length > suffix.length + 2) {
      s = s.slice(0, -suffix.length);
    }
  }
  return s.toLowerCase();
}

function namesMatchFuzzy(poi: SessionPoi, candidate: string): boolean {
  const norm = normalizePoiName(candidate);
  const poiNorm = normalizePoiName(poi.name);
  if (!norm || !poiNorm || norm.length < 2 || poiNorm.length < 2) return false;
  if (norm === poiNorm) return true;
  if (norm.length >= 3 && poiNorm.length >= 3) {
    return norm.includes(poiNorm) || poiNorm.includes(norm);
  }
  return false;
}

function poiIdInText(poi: SessionPoi, text: string): boolean {
  const id = poi.id.trim().replace(/\s+/g, "");
  if (!id) return false;
  return new RegExp(`amap\\.com/place/${escapeRegExp(id)}`, "i").test(text);
}

function stripHeadingTimePrefix(headingContent: string): string {
  return headingContent.replace(HEADING_TIME_PREFIX_RE, "").trim();
}

function isAmapArtifactLine(trimmed: string): boolean {
  if (!trimmed) return false;
  if (trimmed === "]" || trimmed === "(") return true;
  if (IMAGE_LINE_RE.test(trimmed)) return true;
  if (AMAP_MD_LINK_LINE_RE.test(trimmed)) return true;
  if (AMAP_ORPHAN_TAIL_LINE_RE.test(trimmed)) return true;
  if (AMAP_BARE_PAREN_LINE_RE.test(trimmed)) return true;
  if (AMAP_BARE_URL_LINE_RE.test(trimmed)) return true;
  if (/^📍\s*\[[^\]]*\]\(\s*https?:\/\/(?:www\.|uri\.)?amap\.com\/place\//i.test(trimmed)) {
    return true;
  }
  /** 整行仅 `(url)` 或 `(url)，` —— 含后续正文的 `(url)，以室内…` 不算整行 artifact */
  if (new RegExp(String.raw`^\(\s*${AMAP_PLACE_URL}\s*\)\s*[，,、]?\s*$`).test(trimmed)) return true;
  if (/^\]\(\s*https?:\/\/(?:www\.|uri\.)?amap\.com\/place\//i.test(trimmed)) return true;
  if (trimmed.length < 120 && /高德|amap\.com|查看详情|uri\.amap/i.test(trimmed)) return true;
  return false;
}

/** 从 `[` 起吞掉完整 `[alt](amap_url)`（含分店后缀），避免卡嵌后残留 `](url), 人均…` */
function consumeFullMarkdownAmapLinkAt(text: string, start: number): number | null {
  const slice = text.slice(start);
  const m = slice.match(
    new RegExp(String.raw`^\[[^\]]*\]\(\s*${AMAP_PLACE_URL}\s*\)\s*[，,、]?\s*`),
  );
  return m ? start + m[0].length : null;
}

/** POI 名后紧跟的 `(url)` / `](url)` 前缀（保留同行后续描述文字） */
function matchAmapParenPrefix(text: string): RegExpMatchArray | null {
  return (
    text.match(new RegExp(String.raw`^\]\(\s*${AMAP_PLACE_URL}\s*\)\s*[，,、]?\s*`)) ??
    text.match(new RegExp(String.raw`^\(\s*${AMAP_PLACE_URL}\s*\)\s*[，,、]?\s*`))
  );
}

/** 行内 / 跨行残留的高德 place 链（地点栏已展示时去掉） */
function stripAmapPlaceArtifacts(text: string, poiIds: string[]): string {
  let out = text;
  const placeUrl = String.raw`https?:\/\/(?:www\.|uri\.)?amap\.com\/place\/[^)]+`;
  /** `)` 后常见分隔：英文/中文逗号（013 纸箱王 + 本次 B0FFI9ZXCK 变体） */
  const afterParen = String.raw`\s*[，,、]?\s*`;

  out = out.replace(new RegExp(String.raw`\s*!\[[^\]]*\]\([^)]+\)`, "g"), "");
  out = out.replace(new RegExp(String.raw`\s*\[[^\]]*\]\(\s*${placeUrl}\s*\)${afterParen}`, "gi"), "");
  /** 卡嵌后残片：完整 `[name](url)`（须含 `[`，避免只留下 orphan `[`） */
  out = out.replace(new RegExp(String.raw`\[[^\]]*\]\(\s*${placeUrl}\s*\)${afterParen}`, "gi"), "");
  out = out.replace(new RegExp(String.raw`[^\]]*\]\(\s*${placeUrl}\s*\)${afterParen}`, "gi"), "");
  out = out.replace(new RegExp(String.raw`\s*\]\(\s*${placeUrl}\s*\)${afterParen}`, "gi"), "");
  out = out.replace(new RegExp(String.raw`\s*\(\s*${placeUrl}\s*\)${afterParen}`, "gi"), "");
  out = out.replace(new RegExp(String.raw`^\]\(\s*${placeUrl}\s*\)${afterParen}`, "gim"), "");
  out = out.replace(new RegExp(String.raw`^\s*${placeUrl}\s*$`, "gim"), "");
  out = out.replace(new RegExp(String.raw`^\s*!\[[^\]]*\]\([^)]+\)`, "gim"), "");
  out = out.replace(
    new RegExp(String.raw`^📍\s*\[[^\]]*\]\(\s*${placeUrl}\s*\)\s*$`, "gim"),
    "",
  );

  for (const id of poiIds) {
    const normalized = id.trim().replace(/\s+/g, "");
    for (const eid of new Set([id.trim(), normalized].filter(Boolean))) {
      const esc = escapeRegExp(eid);
      const idUrl = String.raw`https?:\/\/(?:www\.|uri\.)?amap\.com\/place\/${esc}[^)]*`;
      out = out.replace(new RegExp(String.raw`\s*\[[^\]]*\]\(\s*${idUrl}\s*\)${afterParen}`, "gi"), "");
      out = out.replace(new RegExp(String.raw`\s*\]\(\s*${idUrl}\s*\)${afterParen}`, "gi"), "");
      out = out.replace(new RegExp(String.raw`\s*\(\s*${idUrl}\s*\)${afterParen}`, "gi"), "");
      out = out.replace(
        new RegExp(String.raw`^📍\s*\[[^\]]*\]\(\s*${idUrl}\s*\)\s*$`, "gim"),
        "",
      );
    }
  }

  out = out.replace(/^\s*[\]\(]\s*$/gm, "");
  out = cleanOrphanLinkBracket(out);
  return out;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 无嵌卡时仅剥 orphan 残片（013/017），不按 place id 误剥合法链接 */
function stripOrphanAmapArtifacts(text: string): string {
  let out = text;
  const placeUrl = String.raw`https?:\/\/(?:www\.|uri\.)?amap\.com\/place\/[^)]+`;
  const afterParen = String.raw`\s*[，,、]?\s*`;
  out = out.replace(new RegExp(String.raw`^\]\(\s*${placeUrl}\s*\)${afterParen}`, "gim"), "");
  out = out.replace(new RegExp(String.raw`^\s*\]\(\s*${placeUrl}\s*\)${afterParen}`, "gim"), "");
  out = out.replace(/^\s*[\]\(]\s*$/gm, "");
  return cleanOrphanLinkBracket(out);
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

/** POI 名外的包裹符：Markdown `[]` 与中文书名号 `「」`（Agent 常见） */
const POI_WRAP_OPEN = /[\[「『]/;
const POI_WRAP_CLOSE = /^[」』\]]\s*/;

function poiEmbedStart(text: string, nameIndex: number): number {
  let i = nameIndex - 1;
  while (i >= 0 && /\s/.test(text[i]!)) i--;
  if (i >= 0 && POI_WRAP_OPEN.test(text[i]!)) return i;
  return nameIndex;
}

function trimTrailingPoiWrappers(text: string): string {
  return text.replace(/[「『\[]\s*$/g, "").replace(/\s+$/g, "");
}

function trimLeadingPoiWrappers(text: string): string {
  return text.replace(/^\s*[」』\]]\s*/g, "");
}

function cleanOrphanLinkBracket(text: string): string {
  return trimLeadingPoiWrappers(
    trimTrailingPoiWrappers(
      text
        .replace(/([：:])\s*\[\s*$/gm, "$1 ")
        .replace(/\[\s*$/gm, "")
        .replace(/^\s*\]\s*$/gm, "")
        .replace(/[「『]\s*$/gm, "")
        .replace(/^\s*[」』]\s*/gm, ""),
    ),
  );
}

/**
 * POI 卡片插入后，跳过紧跟在链接/名称之后的独立图片行（如 store.is.autonavi.com/showpic/…）。
 * 这些行在 POI 卡里已有缩略图，不应再以大图形式渲染。
 */
function skipTrailingPhotoLines(text: string, pos: number): number {
  let end = pos;
  for (;;) {
    const rest = text.slice(end);
    // 仅推进一行：先跳换行符
    const nlMatch = rest.match(/^\r?\n/);
    if (!nlMatch) break;
    const nlLen = nlMatch[0].length;
    const lineEnd = rest.indexOf("\n", nlLen);
    const line = (lineEnd === -1 ? rest.slice(nlLen) : rest.slice(nlLen, lineEnd)).trim();
    if (!line) { end += nlLen; continue; }             // 空行继续
    if (AUTONAVI_PHOTO_RE.test(line) || IMAGE_LINE_RE.test(line)) {
      end += lineEnd === -1 ? rest.length : lineEnd + 1;
      continue;
    }
    break;
  }
  return end;
}

function poiInText(poi: SessionPoi, text: string): boolean {
  return findPoiAnchorInText(text, poi, 0) != null;
}

type PoiAnchor = { idx: number; matchLen: number };

/** 在每日段内定位嵌卡锚点：精确名 → 标题 fuzzy 名 → 同段 place id */
function findPoiAnchorInText(text: string, poi: SessionPoi, cursor: number): PoiAnchor | null {
  const name = poi.name.trim();
  if (name.length >= 2) {
    const exactIdx = text.indexOf(name, cursor);
    if (exactIdx >= 0) return { idx: exactIdx, matchLen: name.length };
  }

  const slice = text.slice(cursor);
  const headingRe = /^#{1,4}\s+(.+)$/gm;
  let hm: RegExpExecArray | null;
  while ((hm = headingRe.exec(slice)) !== null) {
    const lineStart = cursor + hm.index;
    const headingContent = hm[1]!;
    const namePart = stripHeadingTimePrefix(headingContent);
    if (!namesMatchFuzzy(poi, namePart) && !namesMatchFuzzy(poi, headingContent)) continue;
    const nameInLine = namePart ? text.indexOf(namePart, lineStart) : -1;
    if (nameInLine >= 0) return { idx: nameInLine, matchLen: namePart.length };
    return { idx: lineStart, matchLen: headingContent.length };
  }

  const id = poi.id.trim().replace(/\s+/g, "");
  if (!id || !poiIdInText(poi, text.slice(cursor))) return null;

  const idRe = new RegExp(`amap\\.com/place/${escapeRegExp(id)}`, "i");
  const idSlice = text.slice(cursor);
  const im = idRe.exec(idSlice);
  if (!im) return null;

  const urlPos = cursor + im.index;
  const before = text.slice(cursor, urlPos);
  const headings = [...before.matchAll(/^#{1,4}\s+(.+)$/gm)];
  const last = headings[headings.length - 1];
  if (!last) return null;

  const lineStart = cursor + last.index!;
  const headingContent = last[1]!;
  const namePart = stripHeadingTimePrefix(headingContent);
  if (!namesMatchFuzzy(poi, namePart) && !namesMatchFuzzy(poi, headingContent)) return null;

  const nameInLine = namePart ? text.indexOf(namePart, lineStart) : -1;
  if (nameInLine >= 0) return { idx: nameInLine, matchLen: namePart.length };
  return { idx: lineStart, matchLen: headingContent.length };
}

/** 从 POI 名称位置向后吞掉配图、高德链接行（替换为地点栏） */
export function consumePoiMediaAfter(text: string, nameIndex: number, matchLen: number): number {
  let end = nameIndex + matchLen;

  const closeWrap = text.slice(end).match(POI_WRAP_CLOSE);
  if (closeWrap) end += closeWrap[0]!.length;

  const inlineTail = text.slice(end).match(
    new RegExp(String.raw`^[）)]?\s*（?\s*\[[^\]]*\]\(\s*${AMAP_PLACE_URL}\s*\)\s*[，,、]?\s*`),
  );
  if (inlineTail) end += inlineTail[0].length;

  const orphanClose = text.slice(end).match(
    new RegExp(String.raw`^\]\(\s*${AMAP_PLACE_URL}\s*\)\s*[，,、]?\s*`),
  );
  if (orphanClose) end += orphanClose[0].length;

  const bareParen = text.slice(end).match(
    new RegExp(String.raw`^\(\s*${AMAP_PLACE_URL}\s*\)\s*[，,、]?\s*`),
  );
  if (bareParen) end += bareParen[0].length;

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
      if (trimmed === "]") {
        end += lineEnd === -1 ? rest.length : lineEnd + 1;
        continue;
      }
      const prefix = matchAmapParenPrefix(trimmed);
      if (prefix) {
        const leadWs = line.match(/^\s*/)?.[0]?.length ?? 0;
        end += 1 + leadWs + prefix[0]!.length;
        break;
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
  if (!matched.length) {
    return [{ kind: "text", text: stripOrphanAmapArtifacts(dailyText) }];
  }

  const segments: PlanSegment[] = [];
  let cursor = 0;
  const usedIds = new Set<string>();

  while (cursor < dailyText.length) {
    let best: { poi: SessionPoi; anchor: PoiAnchor } | null = null;
    for (const poi of matched) {
      if (usedIds.has(poi.id)) continue;
      const anchor = findPoiAnchorInText(dailyText, poi, cursor);
      if (!anchor) continue;
      if (
        !best ||
        anchor.idx < best.anchor.idx ||
        (anchor.idx === best.anchor.idx && poi.name.length > best.poi.name.length)
      ) {
        best = { poi, anchor };
      }
    }
    if (!best) break;

    const { poi, anchor } = best;
    const { idx, matchLen } = anchor;

    const embedStart = poiEmbedStart(dailyText, idx);
    const fullLinkEnd =
      dailyText[embedStart] === "["
        ? consumeFullMarkdownAmapLinkAt(dailyText, embedStart)
        : null;
    const rawBlockEnd =
      fullLinkEnd != null ? fullLinkEnd : consumePoiMediaAfter(dailyText, idx, matchLen);
    // 消费紧跟在 POI 链接/名称后的独立图片行（POI 卡已有缩略图，不再大图渲染）
    const blockEnd = skipTrailingPhotoLines(dailyText, rawBlockEnd);
    if (embedStart > cursor) {
      // 截取 POI 卡前的文本段，同时去掉紧跟在 POI 名**前面**的图片行（如 "1![](url)"）。
      // 这类图片是模型输出的 POI 配图，POI 卡缩略图已展示，不应再以大图渲染。
      const rawBefore = dailyText.slice(cursor, embedStart);
      const strippedBefore = rawBefore
        .replace(/\n?\d*\s*!\[[^\]]*\]\(https?:\/\/[^)]+\)\s*$/, "")
        .trimEnd();
      const cleanedBefore = cleanOrphanLinkBracket(strippedBefore);
      if (cleanedBefore.trim()) {
        segments.push({ kind: "text", text: cleanedBefore });
      }
    }
    segments.push({ kind: "poi", poi });
    cursor = blockEnd;
    usedIds.add(poi.id);
  }

  if (cursor < dailyText.length) {
    segments.push({
      kind: "text",
      text: cleanOrphanLinkBracket(dailyText.slice(cursor)),
    });
  }

  const embedded = segments.filter((s): s is { kind: "poi"; poi: SessionPoi } => s.kind === "poi");
  const allEmbedded = embedded.map((e) => e.poi);
  const cleaned = segments
    .map((seg) => {
      if (seg.kind !== "text") return seg;
      const text = allEmbedded.length
        ? stripDuplicatePoiMedia(seg.text, allEmbedded)
        : stripOrphanAmapArtifacts(seg.text);
      return text.trim() ? { kind: "text" as const, text } : null;
    })
    .filter((s): s is { kind: "text"; text: string } => s != null);
  return cleaned.length ? cleaned : [{ kind: "text", text: dailyText }];
}

/** 行程速览区纯文本；每日行程区内嵌地点栏并替换配图/链接 */
export function splitPlanWithPois(planText: string, pois: SessionPoi[]): PlanSegment[] {
  const cleaned = stripMovementDiagramSection(planText);
  const dailyStart = findDailySectionStart(cleaned);
  const segments: PlanSegment[] = [];

  if (dailyStart > 0) {
    segments.push({ kind: "text", text: cleaned.slice(0, dailyStart) });
  } else if (dailyStart === cleaned.length) {
    return [{ kind: "text", text: cleaned }];
  }

  const dailyText = cleaned.slice(dailyStart);
  segments.push(...splitDailyWithPois(dailyText, pois));
  return segments;
}
