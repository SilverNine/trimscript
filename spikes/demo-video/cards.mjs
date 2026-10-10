// Caption strips and title / end cards as PNGs, rendered by Chrome so the type is crisp.
import { chromium } from "playwright";
import fs from "node:fs";

// result: the edit's "0:48.1 -> 0:15.2" as `trimscript show` prints it
const [out, result = "0:48.1 -> 0:15.0"] = process.argv.slice(2);
const [from, to] = result.split(" -> ").map((t) => `${Number(t.split(":")[1]).toFixed(1)} s`);
fs.mkdirSync(out, { recursive: true });
// single quotes only: these land inside style="..." attributes
const font = `-apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif`;
const mono = `ui-monospace, 'SF Mono', Menlo, monospace`;

const captions = {
  c1: "A 48-second synthetic demo talk, transcribed on your machine",
  c2: "Delete text, and the video skips it",
  c3: "Trim every um and uh at once. <b>Tab</b> to listen across each edit",
  c4: "Or ask your coding agent: TrimScript ships an MCP server <span class=t>sped up</span>",
  c5: "Every agent edit is a suggestion with a reason. You decide",
  c6: `${from} → ${to}, ready to export as MP4, captions or FCPXML`,
};

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

for (const [name, text] of Object.entries(captions)) {
  await page.setViewportSize({ width: 1920, height: 88 });
  await page.setContent(`<html><body style="margin:0;background:transparent">
    <div style="height:88px;display:flex;align-items:center;justify-content:center;font:500 34px/1 ${font};color:#f4f4f2;letter-spacing:-.01em">
      <span>${text}</span></div>
    <style>b{font-weight:700;color:#fff} .t{margin-left:18px;font:600 18px/1 ${font};color:#111;background:#fbbf24;border-radius:6px;padding:6px 10px;vertical-align:4px}</style></body></html>`);
  await page.screenshot({ path: `${out}/${name}.png`, omitBackground: true });
}

const card = (body) => `<html><body style="margin:0;width:1920px;height:1080px;background:#111;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:34px;font-family:${font};color:#f4f4f2">${body}</body></html>`;
await page.setViewportSize({ width: 1920, height: 1080 });
await page.setContent(card(`
  <div style="font:700 112px/1 ${font};letter-spacing:-.04em">TrimScript</div>
  <div style="font:500 44px/1.2 ${font};color:#cfcfca">Edit video by editing the transcript</div>`));
await page.screenshot({ path: `${out}/title.png` });
await page.setContent(card(`
  <div style="font:700 96px/1 ${font};letter-spacing:-.04em">TrimScript</div>
  <div style="font:500 38px/1.2 ${font};color:#cfcfca">Local · Free · MIT · works with your coding agent</div>
  <div style="margin-top:18px;font:500 27px/1 ${mono};background:#1f1f1f;border:1px solid #333;border-radius:12px;padding:22px 28px;color:#e8e8e3">uvx trimscript open my-video.mp4</div>
  <div style="font:500 30px/1 ${font};color:#9a9a94">github.com/SilverNine/trimscript</div>`));
await page.screenshot({ path: `${out}/end.png` });
await browser.close();
console.log("cards ok");
