# 决赛路演 PPT

生成路径：`lifecare-finals-pitch.pptx`

## 使用的开源 Skill（ClawHub）

| Skill | 来源 | 用途 |
|-------|------|------|
| `@yuchentsai-design/ppt-generator-skill` | ClawHub v4.3 | PptxGenJS 生成流程、`slide_plan.json` 结构、style renderers |
| `@ivangdavila/powerpoint-pptx` | ClawHub v1.0.1 | 排版 QA：内容/占位符匹配、视觉 QA、模板一致性 |
| `@manshan-lin/html-to-pptx` | ClawHub | HTML→PPTX 设计原则（配色占比、避免 AI 装饰线） |
| `@xiangzhanyou/openclaw-ppt-generator` | ClawHub | python-pptx 本地生成参考 |
| `@zachary2024/anthropics-pptx` | ClawHub | Anthropic 官方 pptx 工作流参考 |

Skill 安装目录：`../skills/`

```bash
npx clawhub install @yuchentsai-design/ppt-generator-skill --dir skills
npx clawhub install @ivangdavila/powerpoint-pptx --dir skills
```

## 重新生成

```powershell
cd meituan-lifecare-agent
python scripts/build_pitch_ppt.py
```

流程：
1. Playwright + 本机 Chrome 截取 App mock 四屏 → `assets/`
2. 读取 `slide_plan.json` → `build_deck.mjs`（PptxGenJS）→ `.pptx`

## 改内容

编辑 `slide_plan.json` 后只跑第二步：

```powershell
cd pitch-deck
npm install
node build_deck.mjs
```

## 改截图

编辑 `ui-redesign/app-mocks/app-v1-meituan.html` 后重新跑完整脚本。
