// Shared RFL Academy document template — matches Skateboard Concept Note format.
// Green headings + rules, logo in header (top-right), faint logo watermark,
// "RFL Academy | Innovation Lab" footer. Used by all phase docs + full report.
const fs = require("fs");
const path = require("path");
const {
  Document, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun,
  Header, Footer, AlignmentType, LevelFormat, HeadingLevel, BorderStyle,
  WidthType, ShadingType, VerticalAlign, PageNumber, PageBreak,
  HorizontalPositionAlign, VerticalPositionAlign,
  HorizontalPositionRelativeFrom, VerticalPositionRelativeFrom, TextWrappingType,
} = require("docx");

// ── brand palette ──────────────────────────────────────────
const GREEN   = "00A838";   // headings / footer / rules (brand green, readable)
const GREEN_D = "0B8F33";   // slightly deeper for sub-headings
const TITLE_K = "111111";   // black title (as in sample)
const GREY    = "808080";
const ROW_ALT = "EAF7EF";   // light-green alternating row
const LIGHT   = "F4FBF6";   // code block bg
const CREAM   = "FCF4D8";   // callout bg
const GOLD    = "C79A00";   // callout title accent
const CONTENT_W = 9360;

const ASSETS = __dirname;
const LOGO = fs.readFileSync(path.join(ASSETS, "rfl-logo.png"));
const WM   = fs.readFileSync(path.join(ASSETS, "rfl-watermark.png"));

// PNG IHDR dimension reader (no deps)
function pngSize(buf) {
  return { w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) };
}

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const cellBorders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 80, bottom: 80, left: 120, right: 120 };

// ── headings ───────────────────────────────────────────────
// Big black document title + green subtitle (page-1 top, like the sample)
function titleBlock(title, subtitle) {
  return [
    new Paragraph({ spacing: { before: 120, after: subtitle ? 40 : 160 },
      children: [new TextRun({ text: title, bold: true, color: TITLE_K, size: 56, font: "Arial" })] }),
    ...(subtitle ? [new Paragraph({ spacing: { after: 200 },
      children: [new TextRun({ text: subtitle, bold: true, color: GREEN, size: 26, font: "Arial" })] })] : []),
  ];
}
// Green heading. level 1 → big + rule (numbered sections); 2 → sub; 3 → sub-sub.
function greenHeading(text, level = 1, withRule = level === 1) {
  const sizes = { 1: 32, 2: 25, 3: 22 };
  const hl = { 1: HeadingLevel.HEADING_1, 2: HeadingLevel.HEADING_2, 3: HeadingLevel.HEADING_3 }[level];
  const opt = { heading: hl, spacing: { before: level === 1 ? 260 : 200, after: level === 1 ? 140 : 90 },
    children: [new TextRun({ text, bold: true, color: level >= 3 ? GREEN_D : GREEN, size: sizes[level], font: "Arial" })] };
  if (withRule) opt.border = { bottom: { style: BorderStyle.SINGLE, size: 10, color: GREEN, space: 4 } };
  return new Paragraph(opt);
}
const SEC = (text, num) => greenHeading(num != null ? `${num}. ${text}` : text, 1, true);
const SUBSEC = (text) => greenHeading(text, 2, false);

function P(text, opts = {}) {
  return new Paragraph({ alignment: AlignmentType.JUSTIFIED, spacing: { after: 120, line: 276 },
    children: [new TextRun({ text, size: 22, font: "Arial", ...opts })] });
}
function bullet(text) {
  return new Paragraph({ numbering: { reference: "rfl-bullets", level: 0 }, spacing: { after: 50 },
    children: [new TextRun({ text, size: 22, font: "Arial" })] });
}
function callout(title, body, accent = GOLD, fill = CREAM) {
  const mk = (runs, after) => new Paragraph({ spacing: { after }, children: runs });
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: [CONTENT_W],
    borders: {
      top: { style: BorderStyle.SINGLE, size: 6, color: accent },
      bottom: { style: BorderStyle.SINGLE, size: 6, color: accent },
      right: { style: BorderStyle.SINGLE, size: 6, color: accent },
      left: { style: BorderStyle.SINGLE, size: 18, color: accent } },
    rows: [new TableRow({ children: [new TableCell({
      width: { size: CONTENT_W, type: WidthType.DXA },
      shading: { fill, type: ShadingType.CLEAR },
      margins: { top: 120, bottom: 120, left: 200, right: 200 },
      children: [
        mk([new TextRun({ text: title, bold: true, color: accent, size: 22, font: "Arial" })], 60),
        mk([new TextRun({ text: body, size: 21, font: "Arial", color: "3A3A3A" })], 0) ] })] })] });
}
function code(lines) {
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: [CONTENT_W],
    borders: {
      top: { style: BorderStyle.SINGLE, size: 1, color: "CDE9D6" },
      bottom: { style: BorderStyle.SINGLE, size: 1, color: "CDE9D6" },
      right: { style: BorderStyle.SINGLE, size: 1, color: "CDE9D6" },
      left: { style: BorderStyle.SINGLE, size: 18, color: GREEN } },
    rows: [new TableRow({ children: [new TableCell({
      width: { size: CONTENT_W, type: WidthType.DXA },
      shading: { fill: LIGHT, type: ShadingType.CLEAR },
      margins: { top: 100, bottom: 100, left: 160, right: 120 },
      children: lines.map(l => new Paragraph({ spacing: { after: 0, line: 240 },
        children: [new TextRun({ text: l || " ", font: "Consolas", size: 18, color: "1A1A1A" })] })) })] })] });
}
function dataTable(headers, rows, widths) {
  const headerCells = headers.map((h, i) => new TableCell({
    borders: cellBorders, width: { size: widths[i], type: WidthType.DXA },
    shading: { fill: GREEN, type: ShadingType.CLEAR }, margins: cellMargins, verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({ children: [new TextRun({ text: h, bold: true, color: "FFFFFF", size: 20, font: "Arial" })] })] }));
  const bodyRows = rows.map((r, ri) => new TableRow({
    children: r.map((cellVal, ci) => new TableCell({
      borders: cellBorders, width: { size: widths[ci], type: WidthType.DXA },
      shading: ri % 2 ? { fill: ROW_ALT, type: ShadingType.CLEAR } : undefined, margins: cellMargins,
      children: (Array.isArray(cellVal) ? cellVal : [cellVal]).map(line =>
        new Paragraph({ children: [new TextRun({ text: line, size: 19, font: ci === 0 ? "Consolas" : "Arial" })] })) })) }));
  return new Table({ width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: widths,
    rows: [new TableRow({ tableHeader: true, children: headerCells }), ...bodyRows] });
}
function stepRow(n, title, sub, alt) {
  return new TableRow({ children: [
    new TableCell({ borders: cellBorders, width: { size: 700, type: WidthType.DXA },
      shading: { fill: GREEN, type: ShadingType.CLEAR }, margins: cellMargins, verticalAlign: VerticalAlign.CENTER,
      children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: String(n), bold: true, color: "FFFFFF", size: 24, font: "Arial" })] })] }),
    new TableCell({ borders: cellBorders, width: { size: CONTENT_W - 700, type: WidthType.DXA },
      shading: alt ? { fill: ROW_ALT, type: ShadingType.CLEAR } : undefined, margins: cellMargins,
      children: [
        new Paragraph({ spacing: { after: 30 }, children: [new TextRun({ text: title, bold: true, size: 21, font: "Arial" })] }),
        new Paragraph({ children: [new TextRun({ text: sub, size: 19, color: GREY, font: "Arial" })] }) ] }) ]});
}
function steps(rows) {
  return new Table({ width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: [700, CONTENT_W - 700],
    rows: rows.map((r, i) => stepRow(i + 1, r[0], r[1], i % 2 === 1)) });
}
function imgPlaceholder(caption) {
  const dash = { style: BorderStyle.DASHED, size: 6, color: "AACDB5" };
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: [CONTENT_W],
    borders: { top: dash, bottom: dash, left: dash, right: dash, insideHorizontal: dash, insideVertical: dash },
    rows: [new TableRow({ children: [new TableCell({
      width: { size: CONTENT_W, type: WidthType.DXA },
      margins: { top: 500, bottom: 500, left: 200, right: 200 }, verticalAlign: VerticalAlign.CENTER,
      children: [
        new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 },
          children: [new TextRun({ text: `📷  ${caption}`, bold: true, color: GREEN_D, size: 22, font: "Arial" })] }),
        new Paragraph({ alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "Add screenshot / photo here", italics: true, color: "A8A8A8", size: 18, font: "Arial" })] }) ] })] })] });
}

// ── real images (Phase 1 screenshots) ──────────────────────
function imageRun(buf, maxWpx) {
  const { w, h } = pngSize(buf);
  const width = Math.min(maxWpx, w);
  const height = Math.round(width * h / w);
  return new ImageRun({ type: "png", data: buf, transformation: { width, height },
    altText: { title: "screenshot", description: "screenshot", name: "screenshot" } });
}
function caption(text) {
  return new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 60, after: 160 },
    children: [new TextRun({ text, italics: true, color: GREY, size: 18, font: "Arial" })] });
}
// single centered image with caption
function oneUp(buf, cap, maxWpx = 540) {
  return [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 80, after: 0 },
      children: [imageRun(buf, maxWpx)] }),
    caption(cap),
  ];
}
// two images side by side, each captioned (borderless table)
function twoUp(bufA, capA, bufB, capB, maxWpx = 290) {
  const cell = (buf, cap) => new TableCell({
    borders: { top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE }, left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE } },
    width: { size: CONTENT_W / 2, type: WidthType.DXA }, margins: { top: 40, bottom: 40, left: 80, right: 80 },
    verticalAlign: VerticalAlign.TOP,
    children: [
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 0 }, children: [imageRun(buf, maxWpx)] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 50, after: 0 },
        children: [new TextRun({ text: cap, italics: true, color: GREY, size: 17, font: "Arial" })] }) ] });
  return new Table({ width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: [CONTENT_W / 2, CONTENT_W / 2],
    rows: [new TableRow({ children: [cell(bufA, capA), cell(bufB, capB)] })] });
}

function spacer() { return new Paragraph({ spacing: { after: 120 }, children: [] }); }
function pb() { return new Paragraph({ children: [new PageBreak()] }); }

// ── floating header images (logo top-right + watermark behind) ──
function logoFloat() {
  const { w, h } = pngSize(LOGO); const width = 92; const height = Math.round(width * h / w);
  return new ImageRun({ type: "png", data: LOGO, transformation: { width, height },
    floating: {
      horizontalPosition: { relative: HorizontalPositionRelativeFrom.MARGIN, align: HorizontalPositionAlign.RIGHT },
      verticalPosition: { relative: VerticalPositionRelativeFrom.PAGE, offset: 274320 }, // ~0.3in
      allowOverlap: true, behindDocument: false, wrap: { type: TextWrappingType.NONE } },
    altText: { title: "RFL Academy", description: "RFL Academy logo", name: "logo" } });
}
function watermarkFloat() {
  const { w, h } = pngSize(WM); const width = 460; const height = Math.round(width * h / w);
  return new ImageRun({ type: "png", data: WM, transformation: { width, height },
    floating: {
      horizontalPosition: { relative: HorizontalPositionRelativeFrom.PAGE, align: HorizontalPositionAlign.CENTER },
      verticalPosition: { relative: VerticalPositionRelativeFrom.PAGE, align: VerticalPositionAlign.CENTER },
      allowOverlap: true, behindDocument: true, wrap: { type: TextWrappingType.NONE } },
    altText: { title: "RFL Academy watermark", description: "watermark", name: "watermark" } });
}

function buildDoc({ runningTitle, children }) {
  return new Document({
    features: { updateFields: true },
    styles: {
      default: { document: { run: { font: "Arial", size: 22 } } },
      paragraphStyles: [
        { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 32, bold: true, color: GREEN, font: "Arial" }, paragraph: { outlineLevel: 0 } },
        { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 25, bold: true, color: GREEN, font: "Arial" }, paragraph: { outlineLevel: 1 } },
        { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 22, bold: true, color: GREEN_D, font: "Arial" }, paragraph: { outlineLevel: 2 } },
      ] },
    numbering: { config: [
      { reference: "rfl-bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 540, hanging: 280 } } } }] } ] },
    sections: [{
      properties: { page: { size: { width: 12240, height: 15840 },
        margin: { top: 1300, right: 1440, bottom: 1100, left: 1440, header: 560, footer: 480 } } },
      headers: { default: new Header({ children: [
        new Paragraph({
          spacing: { after: 0 },
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC", space: 6 } },
          children: [
            watermarkFloat(), logoFloat(),
            new TextRun({ text: runningTitle, italics: true, color: GREY, size: 17, font: "Arial" }) ] }) ] }) },
      footers: { default: new Footer({ children: [
        new Paragraph({ alignment: AlignmentType.CENTER,
          border: { top: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC", space: 6 } },
          children: [
            new TextRun({ text: "RFL Academy", bold: true, color: GREEN, size: 18, font: "Arial" }),
            new TextRun({ text: "  |  Innovation Lab", color: GREY, size: 18, font: "Arial" }) ] }) ] }) },
      children,
    }],
  });
}

module.exports = {
  GREEN, GREEN_D, TITLE_K, GREY, CREAM, GOLD, ROW_ALT, CONTENT_W, LOGO, WM, pngSize,
  titleBlock, greenHeading, SEC, SUBSEC, P, bullet, callout, code, dataTable, steps,
  imgPlaceholder, imageRun, oneUp, twoUp, caption, spacer, pb, buildDoc,
};
