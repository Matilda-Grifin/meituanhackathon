/**
 * 路演 PPT — ClawHub ppt-generator-skill + powerpoint-pptx QA 规范
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import pptxgen from "pptxgenjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ASSETS = path.join(__dirname, "assets");
const PLAN_PATH = path.join(__dirname, "slide_plan.json");
const OUT_PATH = path.join(__dirname, process.env.PPT_OUT || "lifecare-finals-pitch.pptx");

const BRAND = "FFC300";
const INK = "1A1A1A";
const BODY = "3D3D3D";
const MUTED = "6B6B6B";
const ORANGE = "FF6B00";
const LIGHT = "FFF8E1";

const plan = JSON.parse(fs.readFileSync(PLAN_PATH, "utf8"));
const FONT_H = plan.font_heading || "Microsoft YaHei";
const FONT_B = plan.font_body || "Microsoft YaHei";
const PHONE_AR = 844 / 390; // phone-screen 高宽比

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.title = plan.title;

const shadow = () => ({
  type: "outer",
  blur: 8,
  offset: 2,
  angle: 135,
  color: "000000",
  opacity: 0.16,
});

function compactHeader(slide, title, subtitle = "") {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06,
    fill: { color: BRAND }, line: { color: BRAND, width: 0 },
  });
  slide.addText(title, {
    x: 0.45, y: 0.12, w: 9.1, h: 0.42,
    fontSize: 22, fontFace: FONT_H, color: INK, bold: true, margin: 0,
  });
  if (subtitle) {
    slide.addText(subtitle, {
      x: 0.45, y: 0.5, w: 9.1, h: 0.28,
      fontSize: 11, fontFace: FONT_B, color: MUTED, margin: 0,
    });
  }
}

function headerBar(slide, title, subtitle = "") {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06,
    fill: { color: BRAND }, line: { color: BRAND, width: 0 },
  });
  slide.addText(title, {
    x: 0.45, y: 0.18, w: 9.1, h: 0.48,
    fontSize: 24, fontFace: FONT_H, color: INK, bold: true, margin: 0,
  });
  if (subtitle) {
    slide.addText(subtitle, {
      x: 0.45, y: 0.64, w: 9.1, h: 0.32,
      fontSize: 12, fontFace: FONT_B, color: MUTED, margin: 0,
    });
  }
}

function addBullets(slide, items, x, y, w, h, size = 13) {
  const runs = items.filter((b) => b !== "").map((b, i, arr) => ({
    text: b,
    options: {
      bullet: !b.startsWith("·") && !/^\d+\./.test(b) && !b.startsWith("术语"),
      breakLine: i < arr.length - 1,
      fontSize: size,
      fontFace: FONT_B,
      color: b.startsWith("术语") ? MUTED : BODY,
      paraSpaceAfter: 6,
      italic: b.startsWith("术语"),
    },
  }));
  if (runs.length) slide.addText(runs, { x, y, w, h, valign: "top", margin: 0 });
}

function addGlossary(slide, lines, y = 4.55, size = 9) {
  if (!lines?.length) return;
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.35, y: y - 0.08, w: 9.3, h: 5.55 - y + 0.05,
    fill: { color: LIGHT }, line: { color: BRAND, width: 0.5 },
  });
  addBullets(slide, lines, 0.5, y, 9.0, 5.5 - y, size);
}

function addPhone(slide, file, x, y, w, caption, captionSize = 10) {
  const imgPath = path.join(ASSETS, file);
  if (!fs.existsSync(imgPath)) return;
  const h = w * PHONE_AR;
  slide.addImage({
    path: imgPath, x, y, w, h,
    // 矩形原图，不做圆角/椭圆裁剪，保证 UI 文字可读
  });
  if (caption) {
    slide.addText(caption, {
      x, y: y + h + 0.04, w, h: 0.55,
      fontSize: captionSize, fontFace: FONT_B, color: INK, bold: true,
      align: "center", valign: "top", margin: 0,
    });
  }
  return h;
}

function layoutPhonesLarge(slide, sd) {
  slide.background = { color: "FFFFFF" };
  compactHeader(slide, sd.title, sd.subtitle);
  const phones = sd.phones || [];
  const n = phones.length;
  const top = 0.82;
  const bottom = sd.footer ? 5.05 : 5.35;
  const capH = 0.58;
  const maxH = bottom - top - capH;
  const gap = n === 3 ? 0.18 : 0.35;
  let phoneW = (9.2 - gap * (n - 1)) / n;
  if (phoneW * PHONE_AR > maxH) phoneW = maxH / PHONE_AR;
  const totalW = n * phoneW + (n - 1) * gap;
  let startX = (10 - totalW) / 2;
  phones.forEach((p) => {
    addPhone(slide, p.file, startX, top, phoneW, p.caption, 9);
    startX += phoneW + gap;
  });
  if (sd.footer) {
    slide.addText(sd.footer, {
      x: 0.4, y: 5.12, w: 9.2, h: 0.38,
      fontSize: 10, fontFace: FONT_B, color: MUTED, align: "center", margin: 0,
    });
  }
}

function layoutContent(slide, sd) {
  slide.background = { color: "FFFFFF" };
  headerBar(slide, sd.title, sd.subtitle);
  const p = sd.phones?.[0];
  const bodyW = p ? 5.4 : 9.0;
  addBullets(slide, sd.body || [], 0.45, 1.05, bodyW, p ? 4.2 : 4.5, 13);
  if (p) {
    addPhone(slide, p.file, p.x ?? 5.95, p.y ?? 0.95, p.w ?? 3.5, p.caption, 10);
  }
  if (sd.footer) {
    slide.addText(sd.footer, {
      x: 0.45, y: 5.15, w: 9.1, h: 0.3,
      fontSize: 10, fontFace: FONT_B, color: MUTED, margin: 0,
    });
  }
}

function layoutImageSplit(slide, sd) {
  slide.background = { color: "FFFFFF" };
  headerBar(slide, sd.title, sd.subtitle);
  const imgPath = path.join(ASSETS, sd.image || "");
  if (fs.existsSync(imgPath)) {
    slide.addImage({
      path: imgPath, x: 0.35, y: 1.0, w: 5.55, h: 3.55,
    });
  }
  addBullets(slide, sd.body || [], 6.05, 1.0, 3.55, 2.5, 11);
  if (sd.glossary) addGlossary(slide, sd.glossary, 4.05, 7.5);
}

function layoutTwoColumn(slide, sd) {
  slide.background = { color: "FFFFFF" };
  headerBar(slide, sd.title, sd.subtitle);
  const body = sd.body || [];
  const split = body.indexOf("—");
  const left = split >= 0 ? body.slice(0, split) : body.slice(0, Math.ceil(body.length / 2));
  const right = split >= 0 ? body.slice(split + 1) : body.slice(Math.ceil(body.length / 2));
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.35, y: 1.0, w: 4.5, h: 4.35,
    fill: { color: LIGHT }, line: { color: BRAND, width: 0.75 }, rectRadius: 0.05,
  });
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.15, y: 1.0, w: 4.5, h: 4.35,
    fill: { color: "FFFFFF" }, line: { color: "E6E6E6", width: 0.75 }, rectRadius: 0.05,
  });
  addBullets(slide, left, 0.5, 1.12, 4.2, 4.1, 12);
  addBullets(slide, right, 5.3, 1.12, 4.2, 4.1, 12);
}

function layoutTable(slide, sd) {
  slide.background = { color: "FFFFFF" };
  compactHeader(slide, sd.title, sd.subtitle);
  const t = sd.table;
  const headerCells = t.headers.map((h) => ({
    text: h,
    options: {
      fill: { color: INK }, color: "FFFFFF", bold: true,
      fontSize: 8, fontFace: FONT_B, align: "center",
    },
  }));
  const dataRows = t.rows.map((row) =>
    row.map((cell) => ({
      text: cell,
      options: { fontSize: 7.5, fontFace: FONT_B, color: BODY, align: "center" },
    }))
  );
  slide.addTable([headerCells, ...dataRows], {
    x: 0.25, y: 0.88, w: 9.5,
    colW: [0.35, 1.85, 0.72, 0.62, 0.62, 0.55, 1.0],
    border: { type: "solid", color: "E0E0E0", pt: 0.5 },
    valign: "middle",
  });
  if (sd.glossary) addGlossary(slide, sd.glossary, 3.78, 7.5);
  if (sd.footer) {
    slide.addText(sd.footer, {
      x: 0.35, y: 5.28, w: 9.3, h: 0.25,
      fontSize: 8, fontFace: FONT_B, color: MUTED, align: "center", margin: 0,
    });
  }
}

function layoutConstraints(slide, sd) {
  slide.background = { color: "FFFFFF" };
  headerBar(slide, sd.title, sd.subtitle);
  const cols = sd.columns || [];
  const cw = 2.95;
  const gap = 0.15;
  cols.forEach((col, i) => {
    const x = 0.35 + i * (cw + gap);
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x, y: 1.05, w: cw, h: 4.35,
      fill: { color: i === 0 ? LIGHT : "FFFFFF" },
      line: { color: i === 0 ? BRAND : "E0E0E0", width: 0.75 },
      rectRadius: 0.05,
    });
    slide.addText(col.title, {
      x: x + 0.12, y: 1.15, w: cw - 0.24, h: 0.35,
      fontSize: 13, fontFace: FONT_H, color: INK, bold: true, margin: 0,
    });
    addBullets(slide, col.items, x + 0.12, 1.55, cw - 0.24, 3.7, 11);
  });
}

function layoutResults(slide, sd) {
  slide.background = { color: "FFFFFF" };
  headerBar(slide, sd.title, sd.subtitle);
  const stats = sd.stats || [];
  const cardW = 2.15;
  const gap = 0.12;
  const total = stats.length * cardW + (stats.length - 1) * gap;
  let x = (10 - total) / 2;
  stats.forEach((s) => {
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x, y: 1.05, w: cardW, h: 1.35,
      fill: { color: "FFFFFF" }, line: { color: BRAND, width: 1 },
      rectRadius: 0.06, shadow: shadow(),
    });
    slide.addText(s.value, {
      x, y: 1.12, w: cardW, h: 0.48,
      fontSize: 22, fontFace: FONT_H, color: ORANGE, bold: true, align: "center", margin: 0,
    });
    slide.addText(s.label, {
      x, y: 1.58, w: cardW, h: 0.3,
      fontSize: 10, fontFace: FONT_B, color: INK, bold: true, align: "center", margin: 0,
    });
    if (s.note) {
      slide.addText(s.note, {
        x, y: 1.88, w: cardW, h: 0.25,
        fontSize: 8, fontFace: FONT_B, color: MUTED, align: "center", margin: 0,
      });
    }
    x += cardW + gap;
  });
  addBullets(slide, sd.body || [], 0.45, 2.55, 9.1, 2.85, 12);
}

function layoutTitle(slide, sd) {
  slide.background = { color: BRAND };
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.1, h: 5.625,
    fill: { color: INK }, line: { color: INK, width: 0 },
  });
  slide.addText(sd.title, {
    x: 0.65, y: 1.55, w: 8.8, h: 1.0,
    fontSize: 42, fontFace: FONT_H, color: INK, bold: true, margin: 0,
  });
  slide.addText(sd.subtitle || "", {
    x: 0.65, y: 2.65, w: 8.8, h: 1.5,
    fontSize: 15, fontFace: FONT_B, color: BODY, margin: 0,
  });
}

function layoutSection(slide, sd) {
  slide.background = { color: BRAND };
  slide.addText(sd.title, {
    x: 0.4, y: 2.15, w: 9.2, h: 0.9,
    fontSize: 38, fontFace: FONT_H, color: INK, bold: true, align: "center", margin: 0,
  });
  if (sd.subtitle) {
    slide.addText(sd.subtitle, {
      x: 0.4, y: 3.05, w: 9.2, h: 0.45,
      fontSize: 17, fontFace: FONT_B, color: BODY, align: "center", margin: 0,
    });
  }
}

const renderers = {
  title: layoutTitle,
  section: layoutSection,
  content: layoutContent,
  "phones-large": layoutPhonesLarge,
  phones: layoutPhonesLarge,
  "two-column": layoutTwoColumn,
  "image-split": layoutImageSplit,
  table: layoutTable,
  constraints: layoutConstraints,
  results: layoutResults,
  stat: layoutResults,
};

for (const sd of plan.slides) {
  const slide = pres.addSlide();
  (renderers[sd.layout] || layoutContent)(slide, sd);
  if (sd.notes) slide.addNotes(sd.notes);
}

await pres.writeFile({ fileName: OUT_PATH });
console.log(JSON.stringify({ status: "ok", output: OUT_PATH, slides: plan.slides.length }));
