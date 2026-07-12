#!/usr/bin/env node
/**
 * 把 Demo HTTPS 地址生成二维码 PNG
 * 用法: node gen-qr.mjs
 *       DEMO_URL=https://example.com node gen-qr.mjs
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import QRCode from 'qrcode';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ASSETS = path.join(__dirname, 'assets');
const OUT = path.join(ASSETS, 'demo-qr.png');
const DEMO_URL = process.env.DEMO_URL || 'https://121.41.81.58:8081';

fs.mkdirSync(ASSETS, { recursive: true });

await QRCode.toFile(OUT, DEMO_URL, {
  type: 'png',
  width: 512,
  margin: 2,
  color: { dark: '#1A1A1A', light: '#FFFFFF' },
  errorCorrectionLevel: 'M',
});

console.log(`✅ 二维码已生成: assets/demo-qr.png`);
console.log(`   内容: ${DEMO_URL}`);
console.log(`   手机扫码即可打开（自签证书需在浏览器点「继续访问」）`);
