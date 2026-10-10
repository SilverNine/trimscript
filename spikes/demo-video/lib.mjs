// Shared by record.mjs (the demo video) and gif.mjs (the README GIF).
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

// a visible cursor and keycaps: headless screencasts show neither
export const overlay = () => {
  const css = `
  #rec-cursor{position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;transform:translate(-3px,-2px);transition:none}
  #rec-ripple{position:fixed;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;border:2px solid #f97316;z-index:2147483646;pointer-events:none;opacity:0}
  #rec-ripple.go{animation:rec-r .45s ease-out}
  @keyframes rec-r{from{opacity:1;transform:scale(.4)}to{opacity:0;transform:scale(1.4)}}
  #rec-keys{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:2147483647;pointer-events:none;display:flex;gap:6px}
  #rec-keys span{font:600 15px/1 -apple-system,system-ui,sans-serif;color:#fff;background:rgba(20,20,20,.86);border-radius:8px;padding:9px 13px;box-shadow:0 4px 14px rgba(0,0,0,.25)}`;
  const add = () => {
    const s = document.createElement("style");
    s.textContent = css;
    document.head.appendChild(s);
    const c = document.createElement("div");
    c.id = "rec-cursor";
    c.innerHTML = `<svg width="22" height="22" viewBox="0 0 24 24"><path d="M4 2l15 11.5-6.6.9 3.9 7.3-2.9 1.5-3.9-7.4L4 20z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
    const r = document.createElement("div");
    r.id = "rec-ripple";
    const k = document.createElement("div");
    k.id = "rec-keys";
    document.body.append(c, r, k);
    addEventListener("mousemove", (e) => (c.style.transform = `translate(${e.clientX - 3}px,${e.clientY - 2}px)`), true);
    addEventListener("mousedown", (e) => {
      r.style.left = e.clientX + "px";
      r.style.top = e.clientY + "px";
      r.classList.remove("go");
      void r.offsetWidth;
      r.classList.add("go");
    }, true);
    const names = { Backspace: "⌫", Enter: "Enter", Tab: "Tab", Escape: "Esc", " ": "Space" };
    let timer = 0;
    addEventListener("keydown", (e) => {
      const n = names[e.key] ?? (e.key.length === 1 ? e.key.toUpperCase() : e.key);
      k.innerHTML = `<span>${(e.shiftKey && e.key !== "Shift" ? "⇧" : "") + n}</span>`;
      clearTimeout(timer);
      timer = setTimeout(() => (k.innerHTML = ""), 900);
    }, true);
  };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", add);
  else add();
};

/** Headless Chrome at 1440x810 CSS px, with the overlay, recording screencast frames into dir. */
export async function open(url, dir, scale = 4 / 3) {
  fs.mkdirSync(dir, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--autoplay-policy=no-user-gesture-required"] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 810 }, deviceScaleFactor: scale });
  await ctx.addInitScript(overlay);
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  const frames = [];
  let n = 0;
  cdp.on("Page.screencastFrame", async ({ data, sessionId }) => {
    const t = Date.now();
    const f = `${String(n++).padStart(5, "0")}.jpg`;
    fs.writeFileSync(path.join(dir, f), Buffer.from(data, "base64"));
    frames.push({ f, t });
    await cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
  });
  await page.goto(url);
  await page.waitForSelector("[data-i]");
  const start = () => cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
  const stop = async () => {
    await cdp.send("Page.stopScreencast");
    await new Promise((r) => setTimeout(r, 300));
    await browser.close();
    return frames;
  };
  return { page, start, stop };
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Mouse helpers that move visibly, so the injected cursor glides instead of jumping. */
export function hands(page) {
  const moveTo = async ([x, y], steps = 22) => page.mouse.move(x, y, { steps });
  // fx: where along the element to click, 0..1 from the left
  const click = async (loc, fx = 0.5) => {
    const b = await loc.boundingBox();
    const at = [b.x + b.width * fx, b.y + b.height / 2];
    await moveTo(at);
    await sleep(150);
    await page.mouse.click(...at);
  };
  const at = async (i, dx = 0.5) => {
    const b = await page.locator(`[data-i="${i}"]`).boundingBox();
    return [b.x + b.width * dx, b.y + b.height / 2];
  };
  const button = (name) => page.getByRole("button", { name, exact: true });
  return { moveTo, click, at, button };
}
