/** 解析 Agent 输出的 2～3 道选择题（支持 A/B/C 或纯文本选项） */

export type IntakeFollowUp = { placeholder: string; optional: boolean };
export type IntakeOption = { letter: string; hint: string; isOther: boolean; followUp?: IntakeFollowUp };
export type IntakeBlock = { n: number; title: string; options: IntakeOption[] };

const OPTION_LETTERS = "A-F";
const FOLLOW_UP_TAG = /\{\{followUp:([^}]+)\}\}/;

/** 问卷展示：去掉模型输出的 Markdown 加粗/星号 */
export function cleanIntakeDisplayText(s: string): string {
  return s
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*\*/g, "")
    .replace(/^\*+\s*|\s*\*+$/g, "")
    .replace(/^[-*•]\s+/, "")
    .trim();
}

const INTAKE_CUT_PATTERNS: RegExp[] = [
  /\n#\s+[🗺️🏙️🌙🌧️]/,
  /\n##\s*📋/,
  /\n##\s*💰/,
  /\n#\s+/,
  /\n---\s*\n/,
  /行程速览/,
  /预算参考/,
];

function findIntakeSoftEnd(src: string): number {
  const lines = src.split("\n");
  let sawQuestion = false;
  let lastOptionLine = -1;
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i]!.trim();
    if (/^\d+[\.、．]\s/.test(t)) sawQuestion = true;
    if (
      /^[A-FＡ-Ｆ][\.、．、：)]/.test(t) ||
      /^[-*•]\s/.test(t) ||
      /^\*\*[A-F]\.\*\*/i.test(t)
    ) {
      lastOptionLine = i;
    }
    if (!sawQuestion || lastOptionLine < 0 || i <= lastOptionLine) continue;
    if (!t) continue;
    const intakeLine =
      /^(\d+[\.、．]|[A-FＡ-Ｆ][\.、．、：)]|[-*•]\s|\*\*[A-F]|全部用默认|直接回复|确认提交)/.test(t);
    if (!intakeLine) {
      let charIdx = 0;
      for (let j = 0; j < i; j++) charIdx += lines[j]!.length + 1;
      return charIdx;
    }
  }
  return src.length;
}

/** 只保留问卷段：遇方案标题/速览即截断，避免 plan 被当选项 */
export function extractIntakeOnlyText(text: string): string {
  const src = text.replace(/\r\n/g, "\n");
  let cut = src.length;
  for (const re of INTAKE_CUT_PATTERNS) {
    const m = src.search(re);
    if (m >= 0) cut = Math.min(cut, m);
  }
  cut = Math.min(cut, findIntakeSoftEnd(src.slice(0, cut)));
  return src.slice(0, cut).trim();
}

/** 问卷段之后的方案正文（用于拆分同行 assistant） */
export function extractIntakeRemainderText(text: string): string {
  const src = text.replace(/\r\n/g, "\n");
  const intakeOnly = extractIntakeOnlyText(text);
  if (!intakeOnly) return src.trim();
  const idx = src.indexOf(intakeOnly);
  if (idx < 0) return "";
  return src.slice(idx + intakeOnly.length).trimStart();
}

function optionIsOther(hint: string): boolean {
  return /其他|自填|请说明|自定义|一句话|都可以/i.test(hint);
}

function parseOptionHint(raw: string): { hint: string; followUp?: IntakeFollowUp } {
  const m = raw.match(FOLLOW_UP_TAG);
  let hint = raw.replace(FOLLOW_UP_TAG, "").trim();
  let followUp: IntakeFollowUp | undefined;
  if (m) {
    followUp = { placeholder: m[1]!.trim(), optional: true };
  } else if (/高铁|动车|火车/i.test(hint)) {
    followUp = { placeholder: "到达/离开站点（选填）及时间", optional: true };
  } else if (/飞机|航班|航站/i.test(hint)) {
    followUp = { placeholder: "到达/离开机场（选填）及时间", optional: true };
  }
  return { hint: cleanIntakeDisplayText(hint).slice(0, 160), followUp };
}

function stripOptionFromTitle(s: string): string {
  return s
    .replace(/\*\*[A-F]\.\*\*\s*.+$/i, "")
    .replace(/^[A-F](?:[\.、．]|\)|）|：)\s*.+$/i, "")
    .trim();
}

function nextAutoLetter(block: IntakeBlock): string {
  const used = new Set(block.options.map((o) => o.letter));
  for (const c of OPTION_LETTERS) {
    if (!used.has(c)) return c;
  }
  return "F";
}

function addIntakeOption(block: IntakeBlock, letter: string, hintRaw: string) {
  const L = letter.toUpperCase();
  const { hint, followUp } = parseOptionHint(hintRaw);
  if (!new RegExp(`^[${OPTION_LETTERS}]$`).test(L) || !hint) return;
  if (!block.options.some((o) => o.letter === L)) {
    block.options.push({ letter: L, hint, isOther: optionIsOther(hint), followUp });
  }
}

function extractBoldOptionsFromLine(line: string, block: IntakeBlock) {
  const re = /\*\*([A-F])\.\*\*\s*([^*]+?)(?=\s*\*\*[A-F]\.\*\*|\s*$)/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(line)) !== null) {
    addIntakeOption(block, m[1]!, m[2]!);
  }
}

function stripMd(line: string): string {
  return cleanIntakeDisplayText(
    line
      .trim()
      .replace(/^\*\*+|\*\*+$/g, "")
      .replace(/^#+\s*/, "")
      .trim(),
  );
}

function isIntakeFooterLine(t: string): boolean {
  return /全部用默认|直接回复|请点击|确认提交|提交所选/i.test(t);
}

function tryParseOptionLine(line: string, block: IntakeBlock): boolean {
  const n0 = block.options.length;
  const t = stripMd(line);
  if (!t || /^#{1,6}\s/.test(t) || isIntakeFooterLine(t)) return false;
  if (/^\d+[\.、．]\s/.test(t)) return false;

  extractBoldOptionsFromLine(t, block);
  if (block.options.length > n0) return true;

  const om = t.match(/^\*\*([A-F])\.\*\*\s*(.+)$/i);
  if (om) {
    addIntakeOption(block, om[1]!, om[2]!);
    return true;
  }
  const plain = t.match(/^([A-FＡ-Ｆ])(?:[\.、．]|\)|）|：)\s*(.+)$/i);
  if (plain) {
    const letter = plain[1]!.normalize("NFKC").toUpperCase().slice(0, 1);
    addIntakeOption(block, letter, plain[2]!);
    return true;
  }
  const listBold = t.match(/^[-*•]\s+\*\*([A-F])\.\*\*\s*(.+)$/i);
  if (listBold) {
    addIntakeOption(block, listBold[1]!, listBold[2]!);
    return true;
  }
  const listPlain = t.match(/^[-*•]\s+([A-F])(?:[\.、．]|\)|）|：)\s*(.+)$/i);
  if (listPlain) {
    addIntakeOption(block, listPlain[1]!, listPlain[2]!);
    return true;
  }
  const bullet = t.match(/^[-*•]\s+(.+)$/);
  if (bullet) {
    const hint = bullet[1]!.trim();
    if (hint.length >= 2 && !/^-{2,}$/.test(hint) && !/^#{1,6}\s/.test(hint)) {
      addIntakeOption(block, nextAutoLetter(block), hint);
    }
    return block.options.length > n0;
  }
  return block.options.length > n0;
}

export function mergeIntakeBlocks(prev: IntakeBlock[] | null, next: IntakeBlock[]): IntakeBlock[] {
  if (!prev?.length) return next;
  const byN = new Map<number, IntakeBlock>();
  for (const b of prev) byN.set(b.n, { ...b, options: [...b.options] });
  for (const b of next) {
    const existing = byN.get(b.n);
    if (!existing) {
      byN.set(b.n, { ...b, options: [...b.options] });
      continue;
    }
    const title = b.title.length >= existing.title.length ? b.title : existing.title;
    const optMap = new Map(existing.options.map((o) => [o.letter, o]));
    for (const o of b.options) optMap.set(o.letter, o);
    byN.set(b.n, {
      n: b.n,
      title,
      options: [...optMap.values()].sort((a, c) => a.letter.localeCompare(c.letter)),
    });
  }
  return [...byN.values()].sort((a, b) => a.n - b.n);
}

function extractIntro(text: string): string {
  const m = text.match(/^([\s\S]*?)(?=\n\s*\d+[\.、．]\s)/);
  if (!m?.[1]) return "";
  return cleanIntakeDisplayText(m[1]!.replace(/^#+\s*/gm, ""));
}

/** 从 assistant 文本解析选择题 + 引导语 */
export function parseIntakeSurvey(text: string): { intro: string; blocks: IntakeBlock[] } {
  const src = extractIntakeOnlyText(text).replace(/\r\n/g, "\n");
  const byN = new Map<number, IntakeBlock>();
  let curN = 0;

  const curBlock = (): IntakeBlock | null => {
    if (curN <= 0) return null;
    let b = byN.get(curN);
    if (!b) {
      b = { n: curN, title: "", options: [] };
      byN.set(curN, b);
    }
    return b;
  };

  const lines = src.split("\n");
  for (const raw of lines) {
    const line = raw.trimEnd();
    const stripped = stripMd(line);
    const qHead = stripped.match(/^(\d+)(?:[\.、．]|\)|）)\s*(.*)$/);
    if (qHead) {
      curN = parseInt(qHead[1]!, 10);
      const rest = (qHead[2] ?? "").trim();
      const b = curBlock()!;
      if (rest) b.title = stripOptionFromTitle(stripMd(rest)) || b.title;
      extractBoldOptionsFromLine(rest, b);
      const imPlain = rest.match(/^([A-F])(?:[\.、．]|\)|）|：)\s*(.+)$/i);
      if (imPlain) addIntakeOption(b, imPlain[1]!, imPlain[2]!);
      continue;
    }
    const b = curBlock();
    if (!b) continue;
    tryParseOptionLine(line, b);
  }

  const sections = src.split(/(?=\n\s*\d+[\.、．]\s*)/);
  for (const sec of sections) {
    const head = sec.match(/^\s*(\d+)[\.、．]\s*([^\n]*)/);
    if (!head) continue;
    const n = parseInt(head[1]!, 10);
    let b = byN.get(n);
    if (!b) {
      b = { n, title: stripOptionFromTitle(head[2] ?? ""), options: [] };
      byN.set(n, b);
    } else if (!b.title && head[2]) {
      b.title = stripOptionFromTitle(head[2]);
    }
    extractBoldOptionsFromLine(sec, b);
    const plainRe = /(?:^|\n)\s*([A-F])(?:[\.、．]|\)|）|：)\s*([^\n]+)/gi;
    let pm: RegExpExecArray | null;
    while ((pm = plainRe.exec(sec)) !== null) {
      addIntakeOption(b, pm[1]!, pm[2]!);
    }
    for (const raw of sec.split("\n").slice(1)) {
      tryParseOptionLine(raw, b);
    }
  }

  const blocks = [...byN.values()]
    .filter((b) => b.options.length > 0)
    .sort((a, c) => a.n - c.n);

  return { intro: extractIntro(src), blocks };
}

export function parseQuestionBlocks(text: string): IntakeBlock[] {
  return parseIntakeSurvey(text).blocks;
}

export function hasIntakeQuestions(text: string): boolean {
  const intakeOnly = extractIntakeOnlyText(text);
  if (parseQuestionBlocks(intakeOnly).length > 0) return true;
  const t = intakeOnly.replace(/\r\n/g, "\n");
  const qs = (t.match(/(?:^|\n)\s*\d+[\.、．]\s/mg) || []).length;
  const opts = (t.match(/(?:^|\n)\s*[A-FＡ-Ｆ][\.、．、：]\s/mg) || []).length;
  return qs >= 1 && opts >= 2;
}
