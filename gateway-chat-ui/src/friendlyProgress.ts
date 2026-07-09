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
  /** B 阶段区域词：首条可见 user 首句（不含 hidden 选择题提交） */
  firstVisibleUserText: string;
  /** A 阶段：自 Send 起经过毫秒（0 = 未在等选择题） */
  intakeWaitElapsedMs: number;
  /** B 阶段（交卷 Send）：自 Send 起经过毫秒 */
  bPhaseWaitElapsedMs: number;
  /** 本轮是否为交卷后的 B 阶段固定叙事轴 */
  bPhaseProgressActive: boolean;
  /** 追问 / 猜你想问 chip：6s×4 叙事轴 */
  followUpProgressActive: boolean;
  agentReplyPending: boolean;
  isFollowUpTurn: boolean;
  resolvedLocation: ResolvedLocation | null;
};

const INTAKE_SUBMISSION_KW_SKIP =
  /^(?:选择题|选项)答案|^全部用默认|^已选[：:]|^第\s*\d+\s*题选/;

const INTAKE_ECHO_STRIP_PREFIX =
  /^(?:我想|我要|帮我|打算|准备|想要|可以|能不能|想在|计划)+/;

const INTAKE_ECHO_SCENE =
  /带娃|情侣|老人|一个人|半日|一天|附近|周边|安静|出片|不折腾|轻松|城里/;

export const INTAKE_PHASE_T1_MS = 4_000;
export const INTAKE_PHASE_T2_MS = 8_000;
export const INTAKE_PHASE_T3_MS = 12_000;

/** B 阶段交卷后：每档展示时长 */
export const B_PHASE_STAGE_MS = 6_000;

/** A 阶段 4～8s：从首句抽 echo 关键词（规则宽，见 014 §2.2） */
export function extractIntakeEchoKeyword(text: string): string {
  const t = text.trim();
  if (!t || INTAKE_SUBMISSION_KW_SKIP.test(t)) return "";

  const mDest = t.match(/去([\u4e00-\u9fff]{2,4})玩/);
  if (mDest) return mDest[1]!;

  if (t.length >= 2 && t.length <= 8 && /^[\u4e00-\u9fff]+$/.test(t)) return t;

  const mPhrase = t.match(/(出去玩|去周边玩?|附近玩)/);
  if (mPhrase) return mPhrase[1]!;

  if (/带娃/.test(t) && /(?:别太折腾|不折腾)/.test(t)) return "带娃不折腾";
  if (/要安静/.test(t) && /出片/.test(t)) return "要安静出片";
  if (/(?:别太折腾|不折腾)/.test(t)) return "别太折腾";
  if (/要安静/.test(t)) return "要安静";

  const mLoc = t.match(/([\u4e00-\u9fff]{2,6}(?:附近|一带|周边))/);
  if (mLoc) return mLoc[1]!.slice(0, 8);

  const scene = t.match(INTAKE_ECHO_SCENE);
  if (scene) return scene[0]!.slice(0, 8);

  const stripped = t.replace(INTAKE_ECHO_STRIP_PREFIX, "").trim();
  const mHead = stripped.match(/^[\u4e00-\u9fff]{2,8}/);
  if (mHead) {
    const kw = mHead[0]!;
    if (!/^(我们|今天|明天|后天|周末)$/.test(kw)) return kw;
  }

  return "";
}

export function formatBPhaseSearchLine(region: string): string {
  const r = region.trim();
  if (!r) return "🔍 搜罗附近好吃的/好逛的…";
  /** 区域词已含 proximity（附近/周边/一带），固定模板不再重复拼「附近」 */
  if (/(?:附近|周边|一带)/.test(r)) return `🔍 搜罗${r}好吃的/好逛的…`;
  return `🔍 搜罗${r}附近好吃的/好逛的…`;
}

export function extractBPhaseRegion(firstVisibleUserText: string, city: string): string {
  const echo = extractIntakeEchoKeyword(firstVisibleUserText);
  if (echo) return echo;
  return city;
}

/** B 阶段交卷后：固定四档，每档 6s，末档停「攻略制定中」 */
export function mapBPhaseProgress(
  elapsedMs: number,
  city: string,
  firstVisibleUserText: string,
): string {
  const region = extractBPhaseRegion(firstVisibleUserText, city);
  const searchLine = formatBPhaseSearchLine(region);
  if (elapsedMs < B_PHASE_STAGE_MS) return searchLine;
  if (elapsedMs < B_PHASE_STAGE_MS * 2) return `🌤 看看${city}天气咋样…`;
  if (elapsedMs < B_PHASE_STAGE_MS * 3) return "🚶 把这几个点给你串成顺路的…";
  return "✍️ 攻略制定中…";
}

/** 追问 / chip · 6～12s：固定句，不 echo 本轮 user 全文 */
export const FOLLOW_UP_REFINE_SEARCH_LINE = "🔍 看看有没有更合你心意的…";

/** 追问 / chip：首档「再改改」，后同 B 轴（省略天气档） */
export function mapFollowUpProgress(elapsedMs: number): string {
  if (elapsedMs < B_PHASE_STAGE_MS) return "✍️ 按你说的再改改路线…";
  if (elapsedMs < B_PHASE_STAGE_MS * 2) return FOLLOW_UP_REFINE_SEARCH_LINE;
  if (elapsedMs < B_PHASE_STAGE_MS * 3) return "🚶 把这几个点给你串成顺路的…";
  return "✍️ 攻略制定中…";
}

export function mapIntakePhaseProgress(
  elapsedMs: number,
  firstVisibleUserText: string,
): string {
  if (elapsedMs < INTAKE_PHASE_T1_MS) {
    return "🔍 听听你这趟想要什么…";
  }
  const echoKw = extractIntakeEchoKeyword(firstVisibleUserText);
  if (elapsedMs < INTAKE_PHASE_T2_MS) {
    if (echoKw) return `💭 ${echoKw}是吧，我再琢磨琢磨…`;
    return "🧩 想想还差啥要问你…";
  }
  if (elapsedMs < INTAKE_PHASE_T3_MS) {
    if (!echoKw) return "✍️ 帮你拟几道好答的题…";
    return "📝 想想还差啥要问你…";
  }
  return "📋 给你列几个选项，马上好…";
}

/** App 移动端进度提示文案（规则映射，无额外 LLM） */
export function mapFriendlyProgress(input: FriendlyProgressInput): {
  main: string;
  sub?: string;
} | null {
  const {
    intakeLocked,
    intakePhasePending,
    showIntakeLoading,
    imageGenPending,
    connected,
    hasVisibleUserMessage,
    firstVisibleUserText,
    intakeWaitElapsedMs,
    bPhaseWaitElapsedMs,
    bPhaseProgressActive,
    followUpProgressActive,
    agentReplyPending,
    isFollowUpTurn,
    resolvedLocation,
    awaitingAgent,
  } = input;

  if (!hasVisibleUserMessage && !agentReplyPending) return null;
  if (!connected) return { main: "网络重连中，稍等一下…" };

  const city = resolvedLocation?.city || resolvedLocation?.district || "当地";
  const pending = agentReplyPending || awaitingAgent;

  if (imageGenPending) return { main: "🎨 给你画张路线一览图…" };

  if (showIntakeLoading || (intakePhasePending && pending)) {
    return {
      main: mapIntakePhaseProgress(
        intakeWaitElapsedMs > 0 ? intakeWaitElapsedMs : 0,
        firstVisibleUserText,
      ),
    };
  }

  if (bPhaseProgressActive && intakeLocked && pending) {
    return {
      main: mapBPhaseProgress(
        bPhaseWaitElapsedMs > 0 ? bPhaseWaitElapsedMs : 0,
        city,
        firstVisibleUserText,
      ),
    };
  }

  if (followUpProgressActive && pending) {
    return {
      main: mapFollowUpProgress(
        bPhaseWaitElapsedMs > 0 ? bPhaseWaitElapsedMs : 0,
      ),
    };
  }

  if (pending) {
    if (isFollowUpTurn) return { main: "✍️ 按你说的再改改路线…" };
    if (intakeLocked) {
      return {
        main: formatBPhaseSearchLine(extractBPhaseRegion(firstVisibleUserText, city)),
      };
    }
    return { main: "✍️ 攻略制定中…" };
  }

  return null;
}

/** 进度提示全集（文档 / 调试对照） */
export const FRIENDLY_PROGRESS_CATALOG: { when: string; main: string }[] = [
  { when: "未连接", main: "网络重连中，稍等一下…" },
  { when: "A · 0～4s", main: "🔍 听听你这趟想要什么…" },
  { when: "A · 4～8s · echo", main: "💭 {关键词}是吧，我再琢磨琢磨…" },
  { when: "A · 4～8s · 无关键词", main: "🧩 想想还差啥要问你…" },
  { when: "A · 8～12s · 有 echo", main: "📝 想想还差啥要问你…" },
  { when: "A · 8～12s · 无 echo", main: "✍️ 帮你拟几道好答的题…" },
  { when: "A · 12s+", main: "📋 给你列几个选项，马上好…" },
  { when: "B · 0～6s", main: "🔍 搜罗{区域}附近好吃的/好逛的…" },
  { when: "B · 6～12s", main: "🌤 看看{城市}天气咋样…" },
  { when: "B · 12～18s", main: "🚶 把这几个点给你串成顺路的…" },
  { when: "B · 18s+", main: "✍️ 攻略制定中…" },
  { when: "追问 · 0～6s", main: "✍️ 按你说的再改改路线…" },
  { when: "追问 · 6～12s", main: "🔍 看看有没有更合你心意的…" },
  { when: "追问 · 12～18s", main: "🚶 把这几个点给你串成顺路的…" },
  { when: "追问 · 18s+", main: "✍️ 攻略制定中…" },
  { when: "行程一览图生成", main: "🎨 给你画张路线一览图…" },
];
