// Record the README GIF: delete the restarted intro, accept filler and pause suggestions, play.
//   node gif.mjs <editor url> <out.gif>
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { hands, open, sleep } from "./lib.mjs";

const [url, out] = process.argv.slice(2);
const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gif-"));
const { page, start, stop } = await open(url, dir, 1);
const { moveTo, click, at, button } = hands(page);
const items = await page.evaluate(async () => (await (await fetch("/api/project")).json()).items);
const first = items.findIndex((it) => it.text === "Hey,");
const last = items.findIndex((it) => it.text === "over.");

await page.mouse.move(980, 560);
await start();
await sleep(1500);
await moveTo(await at(first, 0.15));
await page.mouse.down();
await moveTo(await at(last, 0.9), 30);
await page.mouse.up();
await sleep(600);
await page.keyboard.press("Backspace");
await sleep(1200);
await page.keyboard.press("Escape");
await click(button("Trim fillers"));
await sleep(1200);
for (let k = 0; k < 3; k++) {
  await page.keyboard.press("Tab"); // the next edit, played across
  await sleep(1500);
}
await page.keyboard.press("Escape");
await click(button("Tighten pauses"));
await sleep(1600);
await page.keyboard.press("Escape");
await click(page.getByLabel("Progress through the edit"), 0.01); // back to the start
await sleep(300);
await click(button("Play"));
await sleep(3500);
await click(button("Pause"));
await sleep(1500);
const frames = await stop();

// frames have wall-clock times; hold each until the next, then quantize to 12 fps for the GIF
const list = frames.map((f, i) => `file '${path.join(dir, f.f)}'\nduration ${(((frames[i + 1]?.t ?? f.t + 500) - f.t) / 1000).toFixed(3)}\n`).join("");
fs.writeFileSync(path.join(dir, "list.txt"), list + `file '${path.join(dir, frames.at(-1).f)}'\n`);
execFileSync("ffmpeg", ["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", path.join(dir, "list.txt"),
  "-vf", "fps=12,scale=1200:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle",
  out]);
fs.rmSync(dir, { recursive: true, force: true });
console.log(out, (fs.statSync(out).size / 1e6).toFixed(2), "MB");
