import {
  appendToolProgressStep,
  appendToolStepsFromPayload,
  historyDataUsedSearchPlaces,
} from "../src/toolProgress";
import { isCompleteItineraryPlan, planQualifiesForSearchInference } from "../src/itineraryImage";

const seen = new Set<string>();
let steps = appendToolStepsFromPayload([], {}, seen);

const payloads = [
  { data: { tool: "lifecare__lifecare_get_weather" } },
  { message: { content: [{ type: "toolCall", name: "lifecare__lifecare_search_places" }] } },
  { data: { toolName: "lifecare__lifecare_plan_route" } },
  { message: { content: [{ type: "toolCall", name: "lifecare__lifecare_search_places" }] } },
];

for (const p of payloads) {
  steps = appendToolStepsFromPayload(steps, p, seen);
}

const labels = steps.map((s) => s.msg);
for (const e of ["查询天气", "搜索 POI / 地点", "规划路线"]) {
  if (!labels.includes(e)) {
    console.error("FAIL missing:", e, labels);
    process.exit(1);
  }
}

// 同一轮：结构化已记「查询天气」后，fallback 不应再刷
const seenDup = new Set<string>();
let dupSteps = appendToolStepsFromPayload(
  [],
  { data: { tool: "lifecare__lifecare_get_weather", arguments: { city: "杭州" } } },
  seenDup,
);
for (let i = 0; i < 5; i++) {
  dupSteps = appendToolProgressStep(dupSteps, "查询天气", seenDup);
}
const weatherLines = dupSteps.filter((s) => s.msg === "查询天气" || /^正在查询.+天气/.test(s.msg));
if (weatherLines.length !== 1) {
  console.error("FAIL weather dedup:", weatherLines.length, dupSteps.map((s) => s.msg));
  process.exit(1);
}

const plan =
  "# 测试\n\n## 📋 行程速览\n\n| 时段 | 安排 |\n|---|---|\n| 上午 | 玩 |\n\n" +
  "x".repeat(1300) +
  "\n\n## 💰 预算\n人均 100";

if (!planQualifiesForSearchInference(plan) || !isCompleteItineraryPlan(plan, false)) {
  process.exit(1);
}
if (!historyDataUsedSearchPlaces({ messages: [{ toolName: "lifecare_search_places" }] })) {
  process.exit(1);
}

console.log("OK:", labels.join(" | "));
