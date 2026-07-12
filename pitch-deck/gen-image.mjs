#!/usr/bin/env node
/**
 * 答辩 PPT 生图：OpenRouter GPT 图像模型优先，Seedream 兜底。
 * 参考 accompany/scripts/ark-image.js
 *
 * 用法:
 *   node gen-image.mjs --out assets/journey-5steps.png --ratio 16:9 --prompt "..."
 *   node gen-image.mjs --out assets/journey-5steps.png --prompt-file prompts/journey.txt
 */
import fs from 'fs';
import os from 'os';
import path from 'path';
import https from 'https';
import { execFileSync } from 'child_process';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const SIZE_PRESETS = {
  '1:1': '2048x2048',
  '4:3': '2304x1728',
  '3:4': '1728x2304',
  '16:9': '2560x1440',
  '9:16': '1440x2560',
};

const OPENROUTER_BASE = 'https://openrouter.ai/api/v1';

function loadEnv() {
  const envPath = path.join(__dirname, '.env');
  if (!fs.existsSync(envPath)) {
    throw new Error(`缺少 ${envPath}，请从 .env.example 或 accompany/.env 复制配置`);
  }
  for (const line of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^([^#=]+)=(.*)$/);
    if (m && !process.env[m[1].trim()]) {
      process.env[m[1].trim()] = m[2].trim();
    }
  }
  if (process.env.USE_OVERSEAS_PROXY === '1' && process.env.OVERSEAS_PROXY_HTTPS && !process.env.HTTPS_PROXY) {
    process.env.HTTPS_PROXY = process.env.OVERSEAS_PROXY_HTTPS;
  }
}

function parseArgs(argv) {
  const out = { promptParts: [], ratio: '16:9', out: null, promptFile: null, dryRun: false };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--out' && argv[i + 1]) { out.out = argv[++i]; continue; }
    if (arg === '--ratio' && argv[i + 1]) { out.ratio = argv[++i]; continue; }
    if (arg === '--prompt-file' && argv[i + 1]) { out.promptFile = argv[++i]; continue; }
    if (arg === '--dry-run') { out.dryRun = true; continue; }
    if (arg.startsWith('--')) throw new Error(`未知参数 ${arg}`);
    out.promptParts.push(arg);
  }
  out.prompt = out.promptParts.join(' ').trim();
  if (out.promptFile) {
    out.prompt = fs.readFileSync(path.resolve(__dirname, out.promptFile), 'utf8').trim();
  }
  return out;
}

function isOpenRouterModel(model) {
  return model.includes('/');
}

function getPicturePlan() {
  const primary =
    process.env.picture_model_1 || process.env.PICTURE_MODEL_1 || 'openai/gpt-5.4-image-2';
  const fallback =
    process.env.picture_model_2 ||
    process.env.PICTURE_MODEL_2 ||
    process.env.ARK_PICTURE_MODEL ||
    'doubao-seedream-5-0-260128';

  const plan = [];
  if (primary) plan.push(resolveProvider(primary));
  const fb = resolveProvider(fallback);
  if (!plan.length || plan[plan.length - 1].model !== fb.model) plan.push(fb);
  return plan;
}

function resolveProvider(model) {
  if (isOpenRouterModel(model)) {
    const apiKey = process.env.OPENROUTER_API_KEY;
    if (!apiKey) throw new Error('缺少 OPENROUTER_API_KEY');
    return { provider: 'openrouter', model, apiKey, baseUrl: OPENROUTER_BASE };
  }
  const apiKey = process.env.ARK_API_KEY || process.env.VOLCANO_ENGINE_API_KEY;
  const baseUrl = (process.env.ARK_BASE_URL || 'https://ark.cn-beijing.volces.com/api/v3').replace(/\/$/, '');
  if (!apiKey) throw new Error('缺少 ARK_API_KEY');
  return { provider: 'ark', model, apiKey, baseUrl };
}

function sizeToAspectRatio(size) {
  const map = {
    '2048x2048': '1:1',
    '2304x1728': '4:3',
    '1728x2304': '3:4',
    '2560x1440': '16:9',
    '1440x2560': '9:16',
  };
  return map[size] || '16:9';
}

function decodeDataImageUrl(url) {
  if (!url?.startsWith('data:image')) throw new Error(`非 data:image URL: ${String(url).slice(0, 80)}`);
  const comma = url.indexOf(',');
  if (comma < 0) throw new Error('无效 data URL');
  return Buffer.from(url.slice(comma + 1), 'base64');
}

async function generateOpenRouter({ model, apiKey, prompt, size }) {
  const payload = {
    model,
    messages: [{ role: 'user', content: [{ type: 'text', text: prompt }] }],
    modalities: ['image', 'text'],
    image_config: { aspect_ratio: sizeToAspectRatio(size), image_size: '2K' },
  };

  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pitch-or-'));
  const payloadPath = path.join(tmpDir, 'payload.json');
  fs.writeFileSync(payloadPath, JSON.stringify(payload));

  const proxy = process.env.HTTPS_PROXY || process.env.HTTP_PROXY;
  const curlArgs = ['-sS', '--max-time', '300'];
  if (proxy) curlArgs.push('-x', proxy);
  curlArgs.push(
    '-H', `Authorization: Bearer ${apiKey}`,
    '-H', 'Content-Type: application/json',
    '-d', `@${payloadPath}`,
    `${OPENROUTER_BASE}/chat/completions`,
  );

  let stdout;
  try {
    stdout = execFileSync('curl', curlArgs, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
  } catch (err) {
    throw new Error(String(err.stdout || err.stderr || err.message).slice(0, 500));
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }

  const body = JSON.parse(stdout);
  if (body?.error?.message) throw new Error(body.error.message);
  const images = body?.choices?.[0]?.message?.images || [];
  if (!images.length) throw new Error(`OpenRouter 无图片: ${JSON.stringify(body).slice(0, 300)}`);
  return { buf: decodeDataImageUrl(images[0]?.image_url?.url), usage: body?.usage || null };
}

async function download(url, dest) {
  await new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    https.get(url, (res) => {
      if (res.statusCode >= 400) {
        reject(new Error(`下载失败 HTTP ${res.statusCode}`));
        return;
      }
      res.pipe(file);
      file.on('finish', () => file.close(resolve));
    }).on('error', reject);
  });
}

async function generateArk({ model, apiKey, baseUrl, prompt, size }) {
  const res = await fetch(`${baseUrl}/images/generations`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, prompt, size, response_format: 'url', watermark: false }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body?.error?.message || JSON.stringify(body).slice(0, 400));
  const url = body?.data?.[0]?.url;
  if (!url) throw new Error(`无图片 URL: ${JSON.stringify(body).slice(0, 300)}`);
  const tmp = path.join(os.tmpdir(), `pitch-ark-${Date.now()}.png`);
  await download(url, tmp);
  const buf = fs.readFileSync(tmp);
  fs.unlinkSync(tmp);
  return buf;
}

async function generateImage({ prompt, size }) {
  const plan = getPicturePlan();
  let lastErr;
  for (let i = 0; i < plan.length; i++) {
    const cfg = plan[i];
    const label = i === 0 ? 'primary' : 'fallback';
    try {
      console.error(`[gen-image] 尝试 ${label}: ${cfg.provider}/${cfg.model}`);
      if (cfg.provider === 'openrouter') {
        const result = await generateOpenRouter({ ...cfg, prompt, size });
        return { buf: result.buf, model: cfg.model, usedFallback: i > 0 };
      }
      const buf = await generateArk({ ...cfg, prompt, size });
      return { buf, model: cfg.model, usedFallback: i > 0 };
    } catch (err) {
      lastErr = err;
      console.error(`[gen-image] ${label} 失败: ${err.message || err}`);
    }
  }
  throw lastErr || new Error('生图失败');
}

async function main() {
  loadEnv();
  const args = parseArgs(process.argv.slice(2));
  if (!args.prompt || !args.out) {
    console.error(`用法: node gen-image.mjs --out assets/xxx.png [--ratio 16:9] "提示词"
       或: node gen-image.mjs --out assets/xxx.png --prompt-file prompts/xxx.txt`);
    process.exit(1);
  }

  const size = SIZE_PRESETS[args.ratio] || SIZE_PRESETS['16:9'];
  const negative =
    '不要任何中文字符、不要英文单词、不要乱码假字、不要老年夫妇、不要白发、不要轮椅、不要老伴元素、不要 Q 版动漫、不要 3D 高光渲染、不要深色黑客控制台 UI、不要霓虹赛博朋克、不要素材水印、不要杂乱拼贴。';
  const prompt = `${args.prompt}\n\n负向约束：${negative}`;

  if (args.dryRun) {
    console.log(prompt);
    return;
  }

  const { buf, model, usedFallback } = await generateImage({ prompt, size });
  const outPath = path.resolve(__dirname, args.out);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, buf);
  console.log(`已生成 ${args.out}（${model}${usedFallback ? '，已兜底' : ''}，${size}）`);
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
