// Record the trimscript demo: the editor through Chrome's screencast (crisp JPEG frames with wall-clock
// times), and Claude Code in a terminal through VHS, started mid-way. Usage:
//   node record.mjs <editor url> <out dir> <agent dir>
import { chromium } from "playwright";
import { overlay } from "./lib.mjs";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const [url, out, agentDir] = process.argv.slice(2);
const framesDir = path.join(out, "frames");
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(framesDir, { recursive: true });

const marks = [];
const mark = (name) => {
  marks.push({ name, t: Date.now() });
  console.log("mark", name);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));


const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--autoplay-policy=no-user-gesture-required"] });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 810 }, deviceScaleFactor: 4 / 3 });
await ctx.addInitScript(overlay);
const page = await ctx.newPage();
const cdp = await ctx.newCDPSession(page);
const frames = [];
let n = 0;
cdp.on("Page.screencastFrame", async ({ data, sessionId }) => {
  const t = Date.now();
  const f = `${String(n++).padStart(5, "0")}.jpg`;
  fs.writeFileSync(path.join(framesDir, f), Buffer.from(data, "base64"));
  frames.push({ f, t });
  await cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
});

await page.goto(url);
await page.waitForSelector("[data-i]");
await page.mouse.move(980, 560);
await sleep(800);
// keep frames flowing even when nothing moves, so every second has a picture
await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });

const items = await page.evaluate(async () => (await (await fetch("/api/project")).json()).items);
const idx = (pred, from = 0) => items.findIndex((it, i) => i >= from && pred(it));
const box = async (i) => (await page.locator(`[data-i="${i}"]`).boundingBox());
const at = async (i, dx = 0.5) => {
  const b = await box(i);
  return [b.x + b.width * dx, b.y + b.height / 2];
};
const moveTo = async ([x, y], steps = 22) => page.mouse.move(x, y, { steps });
// fx: where along the element to click, 0..1 from the left
const click = async (loc, fx = 0.5) => {
  const b = await loc.boundingBox();
  const at = [b.x + b.width * fx, b.y + b.height / 2];
  await moveTo(at);
  await sleep(150);
  await page.mouse.click(...at);
};

/** Press Enter on each waiting suggestion in turn, `gap` ms apart. */
async function acceptEach(gap) {
  for (let k = 0; k < 40; k++) {
    const p = await page.evaluate(async () => (await (await fetch("/api/project")).json()).cuts);
    if (!p.some((c) => c.status === "suggested")) return;
    await page.keyboard.press("Enter");
    await sleep(gap);
  }
}

// 1. the transcript
mark("open");
await sleep(2600);

// 2. delete the restarted intro
mark("delete");
const first = idx((it) => it.text === "Hey,");
const last = idx((it) => it.text === "over.");
await moveTo(await at(first, 0.15));
await page.mouse.down();
await moveTo(await at(last, 0.9), 30);
await page.mouse.up();
await sleep(700);
await page.keyboard.press("Backspace");
await sleep(1100);
await page.keyboard.press("Escape");
await click(page.getByRole("button", { name: "Play", exact: true }));
await sleep(2600);
await click(page.getByRole("button", { name: "Pause", exact: true }));
await sleep(500);

// 3. fillers come in as suggestions
mark("fillers");
await click(page.getByRole("button", { name: "Trim fillers", exact: true }));
await sleep(1400);
await page.keyboard.press("Tab"); // step through the edits, each played across
await sleep(2400);
await page.keyboard.press("Tab");
await sleep(2400);
await page.keyboard.press("Escape");
await page.mouse.move(520, 300, { steps: 15 }); // off the toast: hovering pauses it

// 4. ask the agent
mark("agent");
const env = { HOME: process.env.HOME, PATH: process.env.PATH, USER: process.env.USER, LOGNAME: process.env.LOGNAME, SHELL: "/bin/zsh", LANG: "en_US.UTF-8", TERM: "xterm-256color", TMPDIR: process.env.TMPDIR };
const vhsStart = Date.now();
await new Promise((resolve, reject) => {
  const p = spawn("vhs", ["agent.tape"], { cwd: agentDir, env, stdio: "ignore" });
  p.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`vhs exit ${code}`))));
});
mark("agent-done");
marks.push({ name: "vhs-start", t: vhsStart });
await sleep(800);

// 5. review the agent's suggestions
mark("review");
await page.keyboard.press("Tab");
await sleep(3200);
await acceptEach(2600);
await sleep(600);
await page.keyboard.press("Escape");
await click(page.getByLabel("Progress through the edit"), 0.01); // back to the start
await sleep(300);
await click(page.getByRole("button", { name: "Play", exact: true }));
await sleep(4000);
await click(page.getByRole("button", { name: "Pause", exact: true }));
await sleep(1200);
mark("end");

await cdp.send("Page.stopScreencast");
await sleep(300);
await browser.close();
fs.writeFileSync(path.join(out, "frames.json"), JSON.stringify(frames));
fs.writeFileSync(path.join(out, "marks.json"), JSON.stringify(marks, null, 1));
console.log("frames", frames.length);
