/** 用户口语回复 → 尽量映射到 intake 选项（展示用；Agent 仍以原句为准） */

import type { IntakeBlock } from "./intakeParse";

export type IntakeFreetextMatch = {
  selections: Record<number, string>;
  custom: Record<number, string>;
  followUp: Record<number, string>;
};

type QuestionSlot =
  | "scene"
  | "party"
  | "child_age"
  | "child_config"
  | "activity"
  | "museum"
  | "transport"
  | "diet"
  | "duration"
  | "district"
  | "time"
  | "scene_ambiguous"
  | "generic";

function classifyQuestion(title: string, options: IntakeBlock["options"]): QuestionSlot {
  const blob = `${title} ${options.map((o) => o.hint).join(" ")}`;
  const rules: [QuestionSlot, RegExp][] = [
    ["scene_ambiguous", /老婆孩子\s*\/\s*朋友|家人.*朋友/],
    ["scene", /家庭|亲子|带娃|朋友局|和朋友|情侣/],
    ["party", /人数|几个人|总人数|同行|一共/],
    ["child_age", /孩子.*年龄|几岁|幼儿|学前/],
    ["child_config", /成人.*孩子|几大几小|1位成人/],
    ["activity", /活动|类型|倾向|想吃|逛|玩什么/],
    ["museum", /博物馆|展览|手工|亲子互动/],
    ["transport", /交通|出行|地铁|自驾|打车|公交|步行/],
    ["diet", /口味|忌口|饮食|清淡|辣/],
    ["duration", /时长|半天|一天|多久/],
    ["district", /哪个区|所在区|出发|从哪/],
    ["time", /时段|什么时候|今晚|下午|上午/],
  ];
  for (const [slot, re] of rules) {
    if (re.test(blob)) return slot;
  }
  return "generic";
}

function scoreOption(text: string, keywords: string[]): number {
  const t = text.toLowerCase();
  return keywords.reduce((n, k) => (k && t.includes(k.toLowerCase()) ? n + 1 : n), 0);
}

function pickByKeywords(
  block: IntakeBlock,
  keywords: string[],
  fallbackLetter = "A",
  avoid: string[] = [],
): { letter: string; custom: string } {
  let bestL = fallbackLetter;
  let bestS = -1;
  for (const o of block.options) {
    if (avoid.some((a) => o.hint.includes(a))) continue;
    const s = scoreOption(o.hint, keywords);
    if (s > bestS) {
      bestS = s;
      bestL = o.letter;
    }
  }
  if (bestS > 0) return { letter: bestL, custom: "" };
  const other = block.options.find((o) => o.isOther);
  if (other) return { letter: other.letter, custom: keywords.filter(Boolean).slice(0, 3).join("；") };
  return { letter: fallbackLetter, custom: "" };
}

function pickPartyOption(block: IntakeBlock, text: string): { letter: string; custom: string } {
  const m = text.match(/(\d+)\s*人|(\d+)\s*个|(\d+)\s*位|2\s*大\s*1\s*小|1\s*大\s*1\s*小|两大一小|两大两小/);
  if (m) {
    const detail = m[0]!;
    if (/大.*小|小.*大/.test(detail)) {
      return pickByKeywords(block, ["2位成人+1位孩子", "1位成人+1位孩子", "2大1小", "1大1小"], "A");
    }
    const size = parseInt(m[1] || m[2] || m[3] || "0", 10);
    if (size > 0) {
      for (const o of block.options) {
        const nums = [...o.hint.matchAll(/(\d+)\s*人/g)].map((x) => parseInt(x[1]!, 10));
        if (nums.some((n) => n === size)) return { letter: o.letter, custom: "" };
        if (o.hint.includes(String(size))) return { letter: o.letter, custom: "" };
      }
      const other = block.options.find((o) => o.isOther);
      if (other) return { letter: other.letter, custom: `一共${size}人` };
    }
  }
  if (/朋友|同学|聚会/.test(text)) {
    return pickByKeywords(block, ["朋友", "同学", "聚会"], "B", ["老婆", "孩子", "亲子"]);
  }
  if (/家庭|老婆|孩子|亲子|带娃/.test(text)) {
    return pickByKeywords(block, ["家庭", "老婆", "孩子", "亲子", "带娃"]);
  }
  return { letter: "A", custom: "" };
}

function pickForBlock(block: IntakeBlock, text: string): { letter: string; custom: string } {
  const slot = classifyQuestion(block.title, block.options);
  const t = text;

  if (slot === "party" || slot === "child_config") return pickPartyOption(block, t);
  if (slot === "transport") {
    return pickByKeywords(block, [...t.match(/[\u4e00-\u9fff]{2,}/g) ?? [], "地铁", "自驾", "打车", "公交", "步行"]);
  }
  if (slot === "diet") {
    return pickByKeywords(block, [...t.match(/[\u4e00-\u9fff]{2,}/g) ?? [], "清淡", "低油", "微辣", "不辣", "不忌口", "甜"]);
  }
  if (slot === "duration") {
    return pickByKeywords(block, [...t.match(/[\u4e00-\u9fff]{2,}/g) ?? [], "半天", "一天", "几小时", "3小时", "4小时"]);
  }
  if (slot === "time") {
    return pickByKeywords(block, [...t.match(/[\u4e00-\u9fff]{2,}/g) ?? [], "今晚", "下午", "上午", "明天", "周末"]);
  }
  if (slot === "scene" || slot === "scene_ambiguous") {
    if (/朋友|同学|聚会/.test(t)) {
      return pickByKeywords(block, ["朋友", "同学", "聚会"], "B", ["老婆", "孩子"]);
    }
    return pickByKeywords(block, ["家庭", "朋友", "情侣", "亲子", "带娃"]);
  }
  if (slot === "activity" || slot === "museum") {
    return pickByKeywords(block, [...t.match(/[\u4e00-\u9fff]{2,}/g) ?? [], "博物馆", "展览", "咖啡", "火锅", "公园", "商圈", "创意菜"]);
  }
  if (slot === "district") {
    const picked = pickByKeywords(block, [...t.match(/[\u4e00-\u9fff]{2,}/g) ?? []]);
    if (picked.custom || scoreOption(block.options.find((o) => o.letter === picked.letter)?.hint ?? "", [t]) > 0) {
      return picked;
    }
    const other = block.options.find((o) => o.isOther);
    if (other) return { letter: other.letter, custom: t.slice(0, 80) };
  }

  return pickByKeywords(block, [...t.match(/[\u4e00-\u9fff]{2,}/g) ?? []]);
}

/** 从用户一句口语中尽量映射各题选项（未命中则留空，由 Agent 读原句补槽） */
export function matchIntakeFromFreetext(blocks: IntakeBlock[], text: string): IntakeFreetextMatch {
  const selections: Record<number, string> = {};
  const custom: Record<number, string> = {};
  const followUp: Record<number, string> = {};
  const t = text.trim();
  if (!t || !blocks.length) return { selections, custom, followUp };

  for (const block of blocks) {
    const explicit = t.match(new RegExp(`第\\s*${block.n}\\s*题\\s*选\\s*([A-F])`, "i"));
    if (explicit) {
      selections[block.n] = explicit[1]!.toUpperCase();
      continue;
    }
    const letterOnly = t.match(new RegExp(`(?:^|[；;，,\\s])选\\s*([A-F])(?=[；;，,\\s]|$)`, "i"));
    if (letterOnly && blocks.length === 1) {
      selections[block.n] = letterOnly[1]!.toUpperCase();
      continue;
    }
    const picked = pickForBlock(block, t);
    if (picked.letter) {
      selections[block.n] = picked.letter;
      if (picked.custom) custom[block.n] = picked.custom;
    }
  }

  return { selections, custom, followUp };
}
