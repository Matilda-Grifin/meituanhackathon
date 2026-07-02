import type { ResolvedLocation } from "./location";
import type { ProcessStep } from "./toolProgress";

export type FriendlyProgressInput = {
  visibleToolSteps: ProcessStep[];
  awaitingAgent: boolean;
  intakeActive: boolean;
  intakeLocked: boolean;
  intakePhasePending: boolean;
  showIntakeLoading: boolean;
  imageGenPending: boolean;
  connected: boolean;
  hasVisibleUserMessage: boolean;
  streaming: boolean;
  lastUserText: string;
  agentReplyPending: boolean;
  isFollowUpTurn: boolean;
  resolvedLocation: ResolvedLocation | null;
};

function extractUserKeyword(text: string): string {
  const t = text.trim();
  if (!t) return "";
  const m = t.match(/[\u4e00-\u9fff]{2,8}(?:附近|一带|周边)?/);
  return m ? m[0]! : "";
}

function lastStepMsg(steps: ProcessStep[]): string {
  return steps.length ? steps[steps.length - 1]!.msg : "";
}

function extractSearchKeyword(msg: string): string | null {
  const m = msg.match(/正在搜索[「"]([^」"]+)/);
  return m?.[1]?.trim() || null;
}

/** App 移动端进度提示文案（规则映射，无额外 LLM） */
export function mapFriendlyProgress(input: FriendlyProgressInput): {
  main: string;
  sub?: string;
} | null {
  const {
    visibleToolSteps,
    awaitingAgent,
    intakeLocked,
    intakePhasePending,
    showIntakeLoading,
    imageGenPending,
    connected,
    hasVisibleUserMessage,
    lastUserText,
    agentReplyPending,
    isFollowUpTurn,
    resolvedLocation,
  } = input;

  if (!hasVisibleUserMessage && !agentReplyPending) return null;
  if (!connected) return { main: "网络重连中，稍等一下…" };

  const city = resolvedLocation?.city || resolvedLocation?.district || "当地";
  const kw = extractUserKeyword(lastUserText);
  const region = kw || city;
  const last = lastStepMsg(visibleToolSteps);
  const searchKw = extractSearchKeyword(last);

  const pending = agentReplyPending || awaitingAgent;

  if (imageGenPending) return { main: "🎨 给你画张路线一览图…" };

  if (showIntakeLoading || (intakePhasePending && pending)) {
    if (/加载行程规划指引|read/i.test(last)) return { main: "📖 翻翻我的小本本…" };
    return { main: "🔍 听听你这趟想要什么…" };
  }

  if (/查询天气|正在查询.+天气/i.test(last)) {
    return { main: `🌤 看看${city}天气咋样…` };
  }
  if (searchKw) {
    return { main: `🔍 正在查${searchKw}…` };
  }
  if (/搜索|POI|地点/i.test(last)) {
    return { main: `🔍 搜罗${region}附近好吃的/好逛的…` };
  }
  if (/规划路线/i.test(last)) {
    return { main: "🚶 把这几个点给你串成顺路的…" };
  }
  if (/加载行程规划指引/i.test(last)) {
    return { main: "📖 翻翻我的小本本…" };
  }

  if (pending) {
    if (isFollowUpTurn) return { main: "✍️ 按你说的再改改路线…" };
    if (intakeLocked) return { main: `🔍 搜罗${region}附近好吃的/好逛的…` };
    return { main: "✍️ 攻略制定中…" };
  }

  return null;
}

/** 进度提示全集（文档 / 调试对照） */
export const FRIENDLY_PROGRESS_CATALOG: { when: string; main: string }[] = [
  { when: "未连接", main: "网络重连中，稍等一下…" },
  { when: "A 阶段：首句后等选择题", main: "🔍 听听你这趟想要什么…" },
  { when: "A 阶段：read 指引", main: "📖 翻翻我的小本本…" },
  { when: "B 阶段：提交选择题后默认", main: "🔍 搜罗{区域}附近好吃的/好逛的…" },
  { when: "get_weather 工具", main: "🌤 看看{城市}天气咋样…" },
  { when: "search_places（带关键词）", main: "🔍 正在查{关键词}…" },
  { when: "search_places（无关键词）", main: "🔍 搜罗{区域}附近好吃的/好逛的…" },
  { when: "plan_route 工具", main: "🚶 把这几个点给你串成顺路的…" },
  { when: "流式输出方案正文", main: "✍️ 攻略制定中…" },
  { when: "行程一览图生成", main: "🎨 给你画张路线一览图…" },
];
