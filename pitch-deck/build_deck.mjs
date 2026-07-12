/**
 * 星途生活 StarRoute · 决赛路演 PPT 生成
 * 运行: npm install && node build_deck.mjs
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import pptxgen from 'pptxgenjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ASSETS = path.join(__dirname, 'assets');
const OUT = path.join(__dirname, process.env.PITCH_OUT || 'lifecare-finals-pitch.pptx');
const DEMO_URL = process.env.DEMO_URL || 'https://121.41.81.58:8081';

const C = {
  primary: 'FF6633',
  accent: 'FF6B00',
  bg: 'FFF8F5',
  white: 'FFFFFF',
  ink: '1A1A1A',
  body: '333333',
  muted: '666666',
  line: 'E8E8E8',
  phFill: 'F5F0ED',
  phLine: 'FF6633',
};

const W = 10;
const H = 5.625;
const FONT = '微软雅黑';

function withFont(opts = {}) {
  return { fontFace: FONT, ...opts };
}

function asset(name) {
  const p = path.join(ASSETS, name);
  return fs.existsSync(p) ? p : null;
}

/** Demo 二维码：assets/demo-qr.png（npm run gen:qr 生成） */
function addQrCode(slide, pptx, x, y, size, caption) {
  const qr = asset('demo-qr.png');
  if (qr) {
    slide.addImage({ path: qr, x, y, w: size, h: size, sizing: { type: 'contain', w: size, h: size } });
  } else {
    slide.addShape(pptx.shapes.RECTANGLE, {
      x, y, w: size, h: size,
      fill: { color: C.white }, line: { color: C.line, width: 1 },
    });
    slide.addText('QR 占位\nnpm run gen:qr', withFont({
      x, y: y + size * 0.2, w: size, h: size * 0.6, fontSize: 8, color: C.muted, align: 'center', margin: 0,
    }));
  }
  if (caption) {
    slide.addText(caption, withFont({
      x: x - 0.15, y: y + size + 0.04, w: size + 0.3, h: 0.32,
      fontSize: 7.5, color: C.muted, align: 'center', margin: 0,
    }));
  }
}

function slideBg(slide) {
  slide.background = { color: C.bg };
}

function addTopBar(slide, pptx, leftText = '美团 · 点评黑客松 2026') {
  slide.addShape(pptx.shapes.RECTANGLE, {
    x: 0, y: 0, w: W, h: 0.06, fill: { color: C.primary }, line: { color: C.primary },
  });
  slide.addText(leftText, withFont({
    x: 0.4, y: 0.15, w: 5, h: 0.3, fontSize: 9, color: C.muted, margin: 0,
  }));
}

function addTitle(slide, title, y = 0.55) {
  slide.addText(title, withFont({
    x: 0.45, y, w: 9.1, h: 0.55, fontSize: 24, bold: true, color: C.ink, margin: 0,
  }));
}

function addBullets(slide, lines, opts = {}) {
  const items = lines.map((t) => ({
    text: t,
    options: withFont({ bullet: true, breakLine: true, paraSpaceAfter: 6 }),
  }));
  slide.addText(items, withFont({
    x: opts.x ?? 0.45,
    y: opts.y ?? 1.2,
    w: opts.w ?? 5.5,
    h: opts.h ?? 3.8,
    fontSize: opts.fontSize ?? 13,
    color: C.body,
    valign: 'top',
    margin: 0,
  }));
}

function addBody(slide, text, opts = {}) {
  slide.addText(text, withFont({
    x: opts.x ?? 0.45,
    y: opts.y ?? 1.15,
    w: opts.w ?? 9.1,
    h: opts.h ?? 4.2,
    fontSize: opts.fontSize ?? 13,
    color: opts.color ?? C.body,
    valign: 'top',
    margin: 0,
  }));
}

/** 生图占位：虚线框 + 文件名；若 assets 里已有图则直接嵌入 */
function addImageSlot(slide, pptx, filename, x, y, w, h, label) {
  const img = asset(filename);
  if (img) {
    slide.addImage({ path: img, x, y, w, h, sizing: { type: 'contain', w, h } });
    return;
  }
  slide.addShape(pptx.shapes.RECTANGLE, {
    x, y, w, h,
    fill: { color: C.phFill },
    line: { color: C.phLine, width: 1.5, dashType: 'dash' },
  });
  slide.addText([
    { text: '[ 生图占位 ]', options: withFont({ breakLine: true, fontSize: 11, bold: true, color: C.primary }) },
    { text: filename, options: withFont({ breakLine: true, fontSize: 10, color: C.muted }) },
    { text: label || '见 pitch-deck.md 生图提示词', options: withFont({ fontSize: 9, color: C.muted }) },
  ], withFont({
    x: x + 0.15, y: y + h / 2 - 0.45, w: w - 0.3, h: 0.9,
    align: 'center', valign: 'middle', margin: 0,
  }));
}

function addMetricCards(slide, pptx, metrics, y = 2.0) {
  const cardW = 2.85;
  metrics.forEach((m, i) => {
    const x = 0.45 + i * (cardW + 0.2);
    slide.addShape(pptx.shapes.RECTANGLE, {
      x, y, w: cardW, h: 1.85,
      fill: { color: C.white },
      line: { color: C.line, width: 1 },
      shadow: { type: 'outer', blur: 3, offset: 1, angle: 45, opacity: 0.12 },
    });
    slide.addShape(pptx.shapes.RECTANGLE, {
      x, y, w: cardW, h: 0.08, fill: { color: C.primary }, line: { color: C.primary },
    });
    slide.addText(m.num, withFont({
      x, y: y + 0.25, w: cardW, h: 0.7, fontSize: 36, bold: true, color: C.primary, align: 'center', margin: 0,
    }));
    slide.addText(m.label, withFont({
      x: x + 0.15, y: y + 0.95, w: cardW - 0.3, h: 0.35, fontSize: 13, bold: true, color: C.ink, align: 'center', margin: 0,
    }));
    slide.addText(m.desc, withFont({
      x: x + 0.15, y: y + 1.3, w: cardW - 0.3, h: 0.5, fontSize: 10, color: C.muted, align: 'center', margin: 0,
    }));
  });
}

function addTable(slide, headers, rows, opts = {}) {
  const headRow = headers.map((h) => ({
    text: h,
    options: withFont({ fill: { color: C.primary }, color: C.white, bold: true, fontSize: opts.headSize ?? 9 }),
  }));
  const bodyRows = rows.map((row, ri) =>
    row.map((cell, ci) => ({
      text: String(cell),
      options: withFont({
        fontSize: opts.bodySize ?? 8,
        color: C.body,
        fill: { color: ri % 2 === 0 ? C.white : 'FAFAFA' },
        bold: opts.highlightCol === ci,
      }),
    })),
  );
  slide.addTable([headRow, ...bodyRows], {
    x: opts.x ?? 0.35,
    y: opts.y ?? 1.15,
    w: opts.w ?? 9.3,
    colW: opts.colW,
    rowH: opts.rowH ?? 0.28,
    border: { type: 'solid', color: C.line, pt: 0.5 },
    margin: 0,
  });
}

// ─── 构建 ───────────────────────────────────────────────
const pptx = new pptxgen();
pptx.layout = 'LAYOUT_16x9';
pptx.theme = { headFontFace: FONT, bodyFontFace: FONT };
pptx.author = '黄欣媛';
pptx.title = '星途生活 StarRoute · 决赛路演';
pptx.subject = 'AI 本地路线智能规划';

// Slide 01 · 封面
{
  const s = pptx.addSlide();
  slideBg(s);
  s.addShape(pptx.shapes.RECTANGLE, {
    x: 0, y: 0, w: W, h: 0.12, fill: { color: C.primary }, line: { color: C.primary },
  });
  s.addText('美团 · 点评黑客松 2026', withFont({
    x: 0.5, y: 0.22, w: 4, h: 0.3, fontSize: 10, color: C.muted, margin: 0,
  }));
  s.addText('星途生活', withFont({
    x: 0.5, y: 0.75, w: 5.5, h: 0.85, fontSize: 44, bold: true, color: C.ink, margin: 0,
  }));
  s.addText('StarRoute', withFont({
    x: 0.5, y: 1.55, w: 5, h: 0.45, fontSize: 22, color: C.primary, margin: 0,
  }));
  s.addText('顺路 · 一句话，排好你的本地逛吃路线', withFont({
    x: 0.5, y: 2.05, w: 5.8, h: 0.4, fontSize: 16, color: C.body, margin: 0,
  }));
  s.addShape(pptx.shapes.LINE, {
    x: 0.5, y: 2.55, w: 4.5, h: 0, line: { color: C.line, width: 1 },
  });
  s.addText('对话助手：小星', withFont({
    x: 0.5, y: 2.75, w: 5, h: 0.35, fontSize: 14, bold: true, color: C.accent, margin: 0,
  }));
  s.addText('AI 本地路线智能规划  ·  真实地图算路  ·  可照着走的半日行程', withFont({
    x: 0.5, y: 3.15, w: 5.8, h: 0.35, fontSize: 11, color: C.muted, margin: 0,
  }));
  s.addText('黄欣媛  |  浙江大学', withFont({
    x: 0.5, y: 4.85, w: 4, h: 0.3, fontSize: 12, color: C.body, margin: 0,
  }));
  addImageSlot(s, pptx, 'cover-bg.png', 5.9, 0.55, 3.65, 3.5, '封面氛围图（可选）');
  addQrCode(s, pptx, 6.15, 4.15, 1.35, '扫码体验 Demo');
  s.addText(DEMO_URL.replace('https://', ''), withFont({
    x: 5.95, y: 5.52, w: 1.75, h: 0.22, fontSize: 7, color: C.muted, align: 'center', margin: 0,
  }));
}

// Slide 02 · 结论
{
  const s = pptx.addSlide();
  slideBg(s);
  addTopBar(s, pptx);
  addTitle(s, '星途生活：帮用户把半下午逛吃，一次说清楚');
  addBody(s,
    '星途生活 StarRoute 是一款对话式本地路线规划 Agent。用户用口语描述需求，小星先快速问清 2～3 个关键信息，再调用真实地图和天气，输出带时间表、店铺卡片和路线地图的完整方案；之后还能一句话改午饭、改节奏。\n\n和搜索推荐最大的区别：不是扔候选店名单，而是直接交一条排好顺序、算好路程的动线。',
    { y: 1.05, h: 1.5, fontSize: 12 },
  );
  addMetricCards(s, pptx, [
    { num: '< 5 秒', label: '首次可见回应', desc: '选择题或进度提示，不用干等' },
    { num: '90%', label: '规划完整通过率', desc: '50 道测试题批量验证' },
    { num: '≥ 3 个', label: '每方案地点数', desc: '餐饮 + 玩乐/文化两类' },
  ], 2.85);
  addImageSlot(s, pptx, 'metrics-three.png', 7.2, 2.85, 2.35, 1.85, '三数字信息图（可选）');
}

// Slide 03 · 痛点
{
  const s = pptx.addSlide();
  slideBg(s);
  addTopBar(s, pptx);
  addTitle(s, '一次周末出行，用户要在多个 App 之间来回拼');
  addBody(s,
    '周六上午，小陈在美团输入：下午有空，想和朋友在公司附近逛三四个小时，吃点本地的，预算别太高。\n\n典型路径：点评搜展览 → 地图看距离 → 再搜晚餐 → 心算闭馆 → 发现排队太长，重来一遍。同一件事，信息散在三四处，用户自己当调度员。',
    { w: 5.2, h: 2.2, fontSize: 12 },
  );
  addBullets(s, [
    '信息碎片化：店名、评价、距离分散在不同界面',
    '等待没反馈：长时间空白，不知道是在算还是卡死',
    '回答太浅：只给店名，没有先玩哪、再吃哪、怎么过去',
    '结果不稳定：同一句话问两次，质量差很多',
  ], { x: 0.45, y: 3.35, w: 5.2, h: 2.0, fontSize: 11 });
  addImageSlot(s, pptx, 'pain-fragmented.png', 5.85, 1.05, 3.7, 4.2, '痛点插画 · 推荐生图');
}

// Slide 04 · 三个特点
{
  const s = pptx.addSlide();
  slideBg(s);
  addTopBar(s, pptx);
  addTitle(s, '三个特点：快、全、稳');
  addBody(s, '星途生活交付一整条本地路线，不是聊两句推荐三家店。', { y: 1.05, h: 0.4, fontSize: 12 });
  const feats = [
    { t: '快 · 几秒内就有回应', b: '两阶段对话：信息未齐只出点选题，先不查地图；齐了再并行查天气、搜店、算路。多数 < 5 秒可见回应。' },
    { t: '全 · 吃玩都有、地点够', b: '强制餐饮 + 玩乐/文化两类；至少 3 个真实地点，相邻点地图算路，时间表留足移动和用餐。' },
    { t: '稳 · 同一需求，质量不飘', b: '阶段规则 + 四能力模块 + 50 题回归；11 模型横向评测选 Seed Lite。通过率 82%→90%，工具准确率 66%→95%。' },
  ];
  feats.forEach((f, i) => {
    const y = 1.55 + i * 1.25;
    s.addShape(pptx.shapes.RECTANGLE, {
      x: 0.45, y, w: 5.4, h: 1.05,
      fill: { color: C.white }, line: { color: C.line, width: 0.75 },
    });
    s.addShape(pptx.shapes.RECTANGLE, {
      x: 0.45, y, w: 0.08, h: 1.05, fill: { color: C.primary }, line: { color: C.primary },
    });
    s.addText(f.t, withFont({ x: 0.65, y: y + 0.08, w: 5.1, h: 0.32, fontSize: 14, bold: true, color: C.primary, margin: 0 }));
    s.addText(f.b, withFont({ x: 0.65, y: y + 0.42, w: 5.1, h: 0.55, fontSize: 10, color: C.body, margin: 0 }));
  });
  addImageSlot(s, pptx, 'features-three.png', 6.05, 1.45, 3.5, 3.55, '快/全/稳 三列图标 · 推荐生图');
}

// Slide 05 · 产品
{
  const s = pptx.addSlide();
  slideBg(s);
  addTopBar(s, pptx);
  addTitle(s, '星途生活：在对话里交付一整条本地路线');
  addTable(s,
    ['', '传统搜索 / 推荐', '星途生活 StarRoute'],
    [
      ['交付物', '候选列表，用户自己串', '按时间排好的完整行程'],
      ['交互', '表单或多轮搜索', '一句口语 + 点选 · 问小星'],
      ['过程', '常黑盒等待', '气泡内可见查天气、搜店、串路线'],
      ['改需求', '往往重新搜', '原方案上局部修改'],
    ],
    { y: 1.1, colW: [1.2, 3.5, 4.6], highlightCol: 2, bodySize: 11, headSize: 10 },
  );
  addBody(s,
    '对本地生活：把「搜店」推进到「排好一整条」，缩短从想出去玩到敢出门的路径。',
    { y: 4.35, h: 0.6, fontSize: 11, color: C.muted },
  );
}

// Slide 06 · 用户旅程
{
  const s = pptx.addSlide();
  slideBg(s);
  addTopBar(s, pptx);
  addTitle(s, '从小陈的半日下午：五步走完星途生活');
  addImageSlot(s, pptx, 'journey-5steps.png', 0.4, 1.05, 9.2, 2.35, '用户旅程五步信息图 · 强烈推荐');
  const steps = ['① 口语说意图', '② 点选补信息', '③ 看见进展', '④ 完整方案', '⑤ 改方案'];
  steps.forEach((st, i) => {
    s.addText(st, withFont({
      x: 0.45 + i * 1.85, y: 3.55, w: 1.75, h: 0.35, fontSize: 10, bold: true, color: C.primary, align: 'center', margin: 0,
    }));
  });
  addBody(s,
    '小陈，25 岁运营：10 分钟内拿到能照着走的行程。Demo 脚本与这五步一致。',
    { y: 4.05, h: 0.5, fontSize: 11, color: C.muted },
  );
}

// Slide 07 · 体验创新
{
  const s = pptx.addSlide();
  slideBg(s);
  addTopBar(s, pptx);
  addTitle(s, '看起来像消费级产品，不像工程师调试台');
  addBullets(s, [
    '聊天气泡内进度：正在查申园… 单行朋友化，不用底部 debug 时间线',
    '可点选补信息：A/B/C/D 点选，确认前不触发地图重查询',
    '店铺横卡内嵌：图、评分、人均、距离，整卡跳转地图',
    '分层交付：文字先流式 → 地图 → 行程一览图异步插入',
    'UI + 语气双层朋友化：点评橙浅色泡 + 小星口语总评',
  ], { y: 1.1, w: 5.3, fontSize: 12 });
  addImageSlot(s, pptx, 'ux-before-after.png', 5.85, 1.05, 3.7, 4.2, '体验 before/after（可选）');
}

// Slide 08 · 技术
{
  const s = pptx.addSlide();
  slideBg(s);
  addTopBar(s, pptx);
  addTitle(s, '真实数据算路 + 系统护栏，保证又快又稳');
  addBullets(s, [
    '用户 → 对话网关 → 阶段规则 → 四能力模块 → 质量护栏 → 地图/天气 API',
    '两阶段对话：信息齐之前只问问题，不齐不查地图',
    '能力模块拆分：问需求、排行程、算路、读偏好，像插件组合',
    '质量护栏：该查天气时必须查；输出格式坏了自动修',
    'Agent 不是写死脚本：根据真实搜店结果动态调整',
  ], { y: 1.05, w: 5.2, fontSize: 11 });
  addImageSlot(s, pptx, 'arch-diagram.png', 5.75, 1.0, 3.85, 4.25, '架构流程图 · 推荐生图');
}

// Slide 09 · 竞品
{
  const s = pptx.addSlide();
  slideBg(s);
  addTopBar(s, pptx);
  addTitle(s, '朋友感 + 路线深度');
  addTable(s,
    ['维度', 'OTA AI', '独立 App', '点点/小团', '星途生活'],
    [
      ['响应', '快', '参差', '快', '快 <5s'],
      ['复杂条件', '易漏', '弱', '中', '点选+护栏'],
      ['多地点串联', '一般', '不稳', '不稳', '强制算路'],
      ['方案深度', '偏推荐', '偏种草', '偏问答', '完整时间表'],
      ['对话体验', '偏工具', '偏报告', '朋友感', '朋友感+路线'],
    ],
    { y: 1.05, bodySize: 9, headSize: 9, colW: [1.3, 1.5, 1.5, 1.5, 2.0] },
  );
  s.addText('吸收点点/小团的聊天体验，补上 OTA 级路线深度；用真实地图数据保证可落地。', withFont({
    x: 0.45, y: 4.85, w: 9, h: 0.4, fontSize: 11, color: C.primary, margin: 0,
  }));
}

// Slide 10 · 11 模型
{
  const s = pptx.addSlide();
  slideBg(s);
  addTopBar(s, pptx);
  addTitle(s, '11 个模型横向评测 · 选出小星的大脑');
  addTable(s,
    ['#', '模型', '达标率', '全过', '首响', '综合分', '备注'],
    [
      ['1★', 'Seed 2.0 Lite', '96.3%', '2/3', '15.7s', '0.94', '现网默认'],
      ['2', 'DS V4 Flash', '95.8%', '2/3', '19.5s', '0.88', '速度备选'],
      ['3', 'Seed 2.0 Code', '70.4%', '2/3', '24.7s', '0.74', ''],
      ['4', 'Seed 2.0 Pro', '100%', '2/3', '22.8s', '0.73', ''],
      ['5', 'Kimi K2.6', '87.5%', '1/3', '38.2s', '0.71', '首响慢'],
      ['6', 'GLM-4.7', '62.5%', '1/3', '19.0s', '0.70', ''],
      ['7', 'DS V4 Pro', '79.2%', '2/3', '29.2s', '0.69', ''],
      ['8', 'MiniMax M2.7', '62.5%', '1/3', '28.0s', '0.68', ''],
      ['9', 'MiniMax M3', '52.3%', '0/3', '33.7s', '0.55', ''],
      ['10', 'Seed Code', '18.8%', '0/3', '—', '0.18', ''],
      ['11', 'Kimi K2.7 Code', '0%', '0/3', '—', '0.07', ''],
    ],
    { y: 1.0, bodySize: 7.5, headSize: 8, rowH: 0.26, colW: [0.35, 1.55, 0.75, 0.55, 0.65, 0.55, 1.1] },
  );
  s.addText('50 题回归：通过率 82%→90%  ·  工具准确率 66%→95%  ·  Demo 与测评同一套 Agent', withFont({
    x: 0.45, y: 5.05, w: 9, h: 0.35, fontSize: 10, color: C.muted, margin: 0,
  }));
  addImageSlot(s, pptx, 'eval-flow.png', 8.5, 1.0, 1.15, 1.0, '可选');
}

// Slide 11 · Demo
{
  const s = pptx.addSlide();
  slideBg(s);
  addTopBar(s, pptx);
  addTitle(s, '2 分钟 Demo：问小星，跟小陈走同一遍');
  addTable(s,
    ['步骤', '你说', '屏幕应出现'],
    [
      ['1', '下午有空，想和朋友在公司附近逛三四个小时，吃点本地的，预算别太高', '进度 → 2～3 道选择题'],
      ['2', '点选预算/偏好，确认', '搜罗附近 → 查店名 → 串路线'],
      ['3', '等待流式输出', '总览表 → 店铺横卡 → 地图'],
      ['4', '点一家店卡片', '跳转高德店铺页'],
      ['5', '晚饭换一家便宜点的本地小馆，尽量室内', '新进度 → 修订方案'],
    ],
    { y: 1.05, bodySize: 11, headSize: 10, colW: [0.6, 3.8, 4.5] },
  );
  addQrCode(s, pptx, 8.85, 1.05, 1.05, '扫码打开');
  s.addText(DEMO_URL.replace('https://', ''), withFont({
    x: 8.65, y: 2.12, w: 1.45, h: 0.22, fontSize: 7, color: C.muted, align: 'center', margin: 0,
  }));
  s.addShape(pptx.shapes.RECTANGLE, {
    x: 6.2, y: 2.35, w: 2.5, h: 2.95,
    fill: { color: C.white }, line: { color: C.line, width: 1 },
  });
  s.addText('Demo 截图占位\ndemo-*.png', withFont({
    x: 6.2, y: 3.0, w: 2.5, h: 1.2, fontSize: 10, color: C.muted, align: 'center', margin: 0,
  }));
}

// Slide 12 · 自评
{
  const s = pptx.addSlide();
  slideBg(s);
  addTopBar(s, pptx);
  addTitle(s, '完整性 · 创新性 · 应用效果');
  const cols = [
    { h: '完整性', items: ['高德真实店铺与算路', '餐饮+玩乐 ≥3 地点', '时间表闭合、冲突有取舍'] },
    { h: '创新性', items: ['气泡进度、点选、横卡、分层出图', 'LLM+地图+质量护栏', '小星朋友化语气'] },
    { h: '应用效果', items: ['ECS 双端部署 8081/8080', '50 题 90% + 11 模型报告', '文档与脚本可复现'] },
  ];
  cols.forEach((col, i) => {
    const x = 0.45 + i * 3.15;
    s.addShape(pptx.shapes.RECTANGLE, {
      x, y: 1.15, w: 2.95, h: 3.8,
      fill: { color: C.white }, line: { color: C.line, width: 1 },
    });
    s.addText(col.h, withFont({
      x, y: 1.25, w: 2.95, h: 0.4, fontSize: 14, bold: true, color: C.primary, align: 'center', margin: 0,
    }));
    addBullets(s, col.items, { x: x + 0.15, y: 1.75, w: 2.65, h: 3.0, fontSize: 11 });
  });
  s.addText('边界：偏好为模拟语料；本次聚焦路线规划，未做一键订座/下单。', withFont({
    x: 0.45, y: 5.05, w: 9, h: 0.3, fontSize: 9, color: C.muted, margin: 0,
  }));
}

// Slide 13 · 工程
{
  const s = pptx.addSlide();
  slideBg(s);
  addTopBar(s, pptx);
  addTitle(s, '评委可复现：代码、部署、文档');
  addTable(s,
    ['模块', '作用'],
    [
      ['OpenClaw 网关', '多轮对话、流式、会话持久'],
      ['5 能力模块', '问需求 / 排行程 / 算路 / 偏好 / 排队模拟'],
      ['质量护栏', '阶段限制 + 输出修复'],
      ['双端 UI', '8081 答辩 · 8080 调试'],
      ['部署', 'Docker + ECS + Nginx'],
    ],
    { y: 1.1, bodySize: 12, headSize: 11, colW: [2.5, 6.5] },
  );
}

// Slide 14 · 团队
{
  const s = pptx.addSlide();
  slideBg(s);
  addTopBar(s, pptx);
  addTitle(s, '黄欣媛 · 浙江大学');
  s.addShape(pptx.shapes.RECTANGLE, {
    x: 0.45, y: 1.2, w: 2.2, h: 2.8,
    fill: { color: C.phFill }, line: { color: C.line, dashType: 'dash', width: 1 },
  });
  s.addText('照片占位', withFont({
    x: 0.45, y: 2.2, w: 2.2, h: 0.5, fontSize: 11, color: C.muted, align: 'center', margin: 0,
  }));
  addBullets(s, [
    '独立交付：产品 · Agent · 护栏 · 前端 · 测评 · 生图链路 · 部署',
    'Hackathon 周期内完成可演示闭环',
    '架构可按模块对接真实 POI 与交易能力',
  ], { x: 3.0, y: 1.35, w: 6.5, fontSize: 13 });
}

// Slide 15 · 封底
{
  const s = pptx.addSlide();
  slideBg(s);
  addImageSlot(s, pptx, 'closing-bg.png', 0, 0, W, H, '封底背景（可选，有图会铺满）');
  s.addText('星途生活', withFont({
    x: 0.5, y: 1.5, w: 9, h: 0.9, fontSize: 40, bold: true, color: C.ink, align: 'center', margin: 0,
  }));
  s.addText('StarRoute · 顺路', withFont({
    x: 0.5, y: 2.35, w: 9, h: 0.45, fontSize: 20, color: C.primary, align: 'center', margin: 0,
  }));
  s.addText('让附近玩半天，真的只要一句话  ·  对话助手：小星', withFont({
    x: 0.5, y: 2.95, w: 9, h: 0.4, fontSize: 14, color: C.body, align: 'center', margin: 0,
  }));
  addQrCode(s, pptx, 4.35, 3.55, 1.15, '扫码体验');
  s.addText('黄欣媛 · 浙江大学  |  感谢各位评委', withFont({
    x: 0.5, y: 4.5, w: 9, h: 0.35, fontSize: 11, color: C.muted, align: 'center', margin: 0,
  }));
  s.addText(DEMO_URL.replace('https://', ''), withFont({
    x: 3.9, y: 4.72, w: 2.05, h: 0.22, fontSize: 8, color: C.muted, align: 'center', margin: 0,
  }));
}

await pptx.writeFile({ fileName: OUT });
console.log(`✅ 已生成: ${OUT}`);
console.log('📁 生图占位说明: assets/README.md');
console.log('💡 将 PNG 放入 assets/ 后重新运行 node build_deck.mjs 可自动替换占位');
