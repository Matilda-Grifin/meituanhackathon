# 决赛路演 PPT

**输出**：`lifecare-finals-pitch.pptx`  
**文本稿**：`pitch-deck.md`  
**品牌**：星途生活 StarRoute · 顺路 · 对话助手小星  
**字体**：全局微软雅黑

## 重新生成

```powershell
cd meituan-lifecare-agent/pitch-deck
npm install
node build_deck.mjs
```

## 生图（GPT / Seedream）

参考 `accompany` 项目的 OpenRouter + GPT 图像配置：

```powershell
cd meituan-lifecare-agent/pitch-deck
copy .env.example .env
# 或从 D:\projects\accompany\.env 复制 OPENROUTER_API_KEY、picture_model_1 等项

npm run gen:journey          # Slide 06 → assets/journey-5steps.png
npm run gen:image -- --out assets/xxx.png --ratio 16:9 "你的中文提示词"
```

提示词文件：`prompts/journey-5steps.txt`（与 `pitch-deck.md` Slide 06 五步叙事同步）

## 生图替换进 PPT

1. 生图后放入 `assets/`（文件名见 `assets/README.md`）  
2. 重新运行 `node build_deck.mjs`，占位框会自动换成真实图片  

## 页数

15 页：封面 → 结论 → 痛点 → **三个特点（快全稳）** → 产品 → 用户旅程 → 体验 → 技术 → 竞品 → 11 模型 → Demo → 自评 → 工程 → 团队 → 封底
