import type { SessionPoi } from "../../../src/types/sessionPoi";

export type PlanPoiFixture = {
  id: string;
  label: string;
  plan: string;
  pois: SessionPoi[];
  /** 嵌卡后正文里应保留的关键句 */
  expectTextIncludes: string[];
  /** 正文 markdown 段里不应出现的片段 */
  forbidInMarkdown: RegExp[];
};

const photo = "http://store.is.autonavi.com/showpic/example.jpg";

/** 来自 013 文档 + 线上真实变体 */
const cartonKing: PlanPoiFixture = {
  id: "013-carton-king",
  label: "013 纸箱王 · id 含空格 + 英文逗号",
  plan: `# 半日行程

## 行程速览
| 时段 | 做什么 |
| ---- | ------ |
| 12:30 | 午餐 |

## 分行程详细说明
### 12:30-13:30 午餐
[纸箱王纸火锅主题餐厅(联明路店)](https://www.amap.com/place/B0FFGCTL MQ), 全程约20公里，车程约45分钟，适合带娃。`,
  pois: [
    {
      id: "B0FFGCTLMQ",
      name: "纸箱王纸火锅主题餐厅",
      amap_place_url: "https://www.amap.com/place/B0FFGCTLMQ",
      photo_urls: [photo],
      rating: 4.6,
      cost: "88",
    },
  ],
  expectTextIncludes: ["全程约20公里", "适合带娃"],
  forbidInMarkdown: [/amap\.com\/place/i, /^\]/m, /^\(/m],
};

/** 来自 017 文档 */
const indoorFlowers: PlanPoiFixture = {
  id: "017-indoor-flowers",
  label: "017 B0FFI9ZXCK · 中文逗号同行",
  plan: `# 一日行程

## 分行程详细说明
### 14:00 参观
[上海某室内花园](https://www.amap.com/place/B0FFI9ZXCK)，以室内花卉观赏和休闲为主，餐厅安排不变。`,
  pois: [
    {
      id: "B0FFI9ZXCK",
      name: "上海某室内花园",
      amap_place_url: "https://www.amap.com/place/B0FFI9ZXCK",
      photo_urls: [photo],
    },
  ],
  expectTextIncludes: ["以室内花卉观赏和休闲为主", "餐厅安排不变"],
  forbidInMarkdown: [/amap\.com\/place/i, /^\]/m],
};

/** 来自用户截图：短 session 名 + 括号分店 + ](url), 人均… */
const luckinCoffee: PlanPoiFixture = {
  id: "user-luckin-branch",
  label: "用户截图 luckin · 短名嵌卡 + 分店后缀残片",
  plan: `# 半日行程

## 分行程详细说明
### 12:00 咖啡
[luckin coffee(联明路店)](https://www.amap.com/place/B0FFKXLEN4), 人均仅需十几元，选择也很丰富。

### 12:40 午餐
[纸箱王纸火锅主题餐厅(联明路店)](https://www.amap.com/place/B0FFKXLEN4), 纸火锅体验不错。`,
  pois: [
    {
      id: "B0FFKXLEN4",
      name: "luckin coffee",
      amap_place_url: "https://www.amap.com/place/B0FFKXLEN4",
      photo_urls: [photo],
      cost: "15",
    },
    {
      id: "B0CARTONKING",
      name: "纸箱王纸火锅主题餐厅",
      amap_place_url: "https://www.amap.com/place/B0CARTONKING",
      photo_urls: [photo],
    },
  ],
  expectTextIncludes: ["人均仅需十几元", "选择也很丰富", "纸火锅体验不错"],
  forbidInMarkdown: [/amap\.com\/place/i, /\]\(/],
};

/** 来自 _tmp_plan.txt 真实输出片段 */
const shanghaiMuseum: PlanPoiFixture = {
  id: "tmp-shanghai-museum",
  label: "_tmp_plan 上海自然博物馆",
  plan: `# 上海闵行区半日

## 行程速览
| 时段 | 做什么 |
| ---- | ------ |
| 10:00 | 参观博物馆 |

## 分行程详细说明
### 10:00-12:30 参观 [上海自然博物馆](https://www.amap.com/place/B00156NVZG)

![](http://store.is.autonavi.com/showpic/239f758f8beacd1c49af5dc7677810e4)

上海自然博物馆是上海最受欢迎的亲子科教场馆之一，高德评分高达4.8分。`,
  pois: [
    {
      id: "B00156NVZG",
      name: "上海自然博物馆",
      amap_place_url: "https://www.amap.com/place/B00156NVZG",
      photo_urls: [photo],
      rating: 4.8,
    },
  ],
  expectTextIncludes: ["上海自然博物馆是上海最受欢迎", "4.8分"],
  forbidInMarkdown: [/amap\.com\/place/i],
};

const neobioLilliput: PlanPoiFixture = {
  id: "018-neobio-lilliput",
  label: "018 奈尔宝/粒粒堡 · API 名与正文不一致",
  plan: `# 上海市闵行区半天带娃城市休闲出行方案

## 行程速览
| 时段 | 安排 |
| ---- | ---- |
| 09:30 | 奈尔宝 |

## 分时段详细安排

### 09:30 - 12:00 奈尔宝·儿童乐园·亲子餐厅（上海爱琴海店）
📍 [吴中路1588号上海爱琴海购物中心1F](https://www.amap.com/place/B0J25HS4G5)  
⏱ 建议停留：2.5小时  
💡 推荐理由：距离出发地仅不到3公里，完全不折腾。

![](https://store.is.autonavi.com/showpic/088af762109a75fd0000002099144838?type=pic)

### 12:10 - 14:00 Lilliput粒粒堡亲子餐厅（七宝宝龙城店）
📍 [漕宝路3299号七宝宝龙城沿河独栋别墅9号楼](https://www.amap.com/place/B0L3FR65ED)  
⏱ 建议停留：1.5-2小时  
💡 推荐理由：从奈尔宝开车过来仅需14分钟。`,
  pois: [
    {
      id: "B0J25HS4G5",
      name: "奈尔宝·儿童乐园·亲子餐厅(上海爱琴海店)",
      amap_place_url: "https://www.amap.com/place/B0J25HS4G5",
      photo_urls: [photo],
      rating: 4.6,
      cost: "175.00",
    },
    {
      id: "B0L3FR65ED",
      name: "Lilliput粒粒堡(七宝宝龙城)",
      amap_place_url: "https://www.amap.com/place/B0L3FR65ED",
      photo_urls: [photo],
      rating: 4.5,
      cost: "159.00",
    },
  ],
  expectTextIncludes: ["建议停留：2.5小时", "完全不折腾", "从奈尔宝开车过来仅需14分钟"],
  forbidInMarkdown: [/amap\.com\/place/i, /!\[/],
};

/** 中文书名号包裹店名：嵌卡后不应残留 「」 */
const minhangMuseumCorner: PlanPoiFixture = {
  id: "019-minhang-museum-corner",
  label: "019 闵行博物馆 · 「」包裹名",
  plan: `# 半日行程

## 行程速览
| 时段 | 安排 |
| ---- | ---- |
| 09:30 | 博物馆 |

## 分时段详细安排
### 09:30-12:00 参观 「闵行博物馆」

闵行博物馆位于闵行区新镇路1538号，适合带娃参观。`,
  pois: [
    {
      id: "B0HGRCVJ1L",
      name: "闵行博物馆",
      amap_place_url: "https://www.amap.com/place/B0HGRCVJ1L",
      photo_urls: [photo],
      rating: 4.7,
    },
  ],
  expectTextIncludes: ["位于闵行区新镇路1538号", "适合带娃参观"],
  forbidInMarkdown: [/[\[「\]」]/],
};

/** 无 POI 名匹配时也应剥离 orphan 残片（017 stripOnly） */
const stripOnly: PlanPoiFixture = {
  id: "017-strip-fallback",
  label: "无嵌卡 · session pois 兜底剥离",
  plan: `# 行程

## 分行程详细说明
### 15:00
](https://www.amap.com/place/B0FFI9ZXCK), 以室内花卉观赏和休闲为主。`,
  pois: [
    {
      id: "B0FFI9ZXCK",
      name: "完全不匹配的店名XYZ",
      amap_place_url: "https://www.amap.com/place/B0FFI9ZXCK",
      photo_urls: [],
    },
  ],
  expectTextIncludes: ["以室内花卉观赏和休闲为主"],
  forbidInMarkdown: [/amap\.com\/place/i, /\]\(/],
};

export const PLAN_POI_FIXTURES: PlanPoiFixture[] = [
  cartonKing,
  indoorFlowers,
  luckinCoffee,
  shanghaiMuseum,
  neobioLilliput,
  minhangMuseumCorner,
  stripOnly,
];
