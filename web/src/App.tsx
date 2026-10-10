import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AudioLines, Bot, Download, Eraser, Eye, EyeOff, Pause, Play, Redo2, Sparkles, Timer, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Kbd } from "@/components/ui/kbd";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Toggle } from "@/components/ui/toggle";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Cut, ExportState, Item, Project, exportStatus, getProject, op, startExport } from "./api";

type ItemState = { cut: Cut } | null;
type Sel = { anchor: number; focus: number } | null;

const LISTEN_PAD = 1.5;

function fmt(t: number): string {
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

/** Map a source time to the edited timeline. */
function editedTime(t: number, removed: [number, number][]): number {
  let shift = 0;
  for (const [lo, hi] of removed) {
    if (hi <= t) shift += hi - lo;
    else if (lo < t) shift += t - lo;
  }
  return t - shift;
}

/** Map a time on the edited timeline back to the source. */
function sourceTime(e: number, removed: [number, number][]): number {
  let t = e;
  for (const [lo, hi] of removed) {
    if (lo <= t) t += hi - lo;
    else break;
  }
  return t;
}

function itemStates(p: Project): ItemState[] {
  const idx = new Map(p.items.map((it, i) => [it.id, i]));
  const out: ItemState[] = p.items.map(() => null);
  // accepted cuts win over suggestions on the same item
  const ordered = [...p.cuts].sort((a, b) => (a.status === b.status ? 0 : a.status === "accepted" ? 1 : -1));
  for (const c of ordered) {
    const a = idx.get(c.first);
    const b = idx.get(c.last);
    if (a === undefined || b === undefined) continue;
    for (let i = Math.min(a, b); i <= Math.max(a, b); i++) out[i] = { cut: c };
  }
  return out;
}

function paragraphs(items: Item[]): [number, number][] {
  const out: [number, number][] = [];
  let lo = 0;
  let words = 0;
  items.forEach((it, i) => {
    words++;
    const next = items[i + 1];
    const sentenceEnd = /[.?!]$/.test(it.text);
    const longPause = next?.kind === "pause" && next.end - next.start >= 1.5;
    if (i === items.length - 1 || (sentenceEnd && (longPause || words > 60))) {
      out.push([lo, i]);
      lo = i + 1;
      words = 0;
    }
  });
  return out;
}

/** Seconds of the removed ranges that fall between two times. */
function removedBetween(removed: [number, number][], lo: number, hi: number): number {
  let sum = 0;
  for (const [a, b] of removed) sum += Math.max(0, Math.min(b, hi) - Math.max(a, lo));
  return sum;
}

interface ParaProps {
  lo: number;
  hi: number;
  sig: string; // cut state of this paragraph; unchanged paragraphs skip rendering
  items: Item[];
  states: ItemState[];
  removed: [number, number][];
  showRemoved: boolean;
  selLo: number;
  selHi: number;
  onDown: (i: number, e: React.MouseEvent, j?: number) => void;
  onEnter: (i: number, j?: number) => void;
  onDouble: (i: number) => void;
}

const Paragraph = memo(function Paragraph({ lo, hi, items, states, removed, showRemoved, selLo, selHi, onDown, onEnter, onDouble }: ParaProps) {
  const spans = [];
  for (let i = lo; i <= hi; i++) {
    const it = items[i];
    const st = states[i];
    if (st?.cut.status === "accepted" && !showRemoved) {
      // fold the whole removed run into one label; selecting it selects the run
      let j = i;
      while (j < hi && states[j + 1]?.cut.id === st.cut.id) j++;
      const secs = removedBetween(removed, items[i - 1]?.end ?? 0, items[j + 1]?.start ?? Infinity);
      const text = items.slice(i, j + 1).filter((x) => x.kind === "word" || x.kind === "filler").map((x) => x.text).filter(Boolean).join(" ");
      if (spans.length) spans.push(" ");
      spans.push(
        <span
          key={it.id}
          data-i={i}
          className={`tok fold ${i >= selLo && j <= selHi ? "sel" : ""}`}
          title={text ? `Removed: ${text}` : "Removed"}
          onMouseDown={(e) => onDown(i, e, j)}
          onMouseEnter={() => onEnter(i, j)}
        >
          −{secs.toFixed(1)} s
        </span>,
      );
      i = j;
      continue;
    }
    if ((it.kind === "word" || it.kind === "filler") && !it.text) continue; // emptied by a correction
    if (spans.length) spans.push(" "); // real spaces, so lines can wrap between words
    const cls = [
      "tok",
      it.kind,
      st ? (st.cut.status === "accepted" ? "cut" : "sugg") : "",
      i >= selLo && i <= selHi ? "sel" : "",
    ].join(" ");
    spans.push(
      <span
        key={it.id}
        data-i={i}
        className={cls}
        title={st?.cut.reason || (it.kind === "sound" ? "Voice here but no word. Select it and press L to listen." : undefined)}
        onMouseDown={(e) => onDown(i, e)}
        onMouseEnter={() => onEnter(i)}
        onDoubleClick={() => onDouble(i)}
      >
        {it.kind === "pause" ? `${(it.end - it.start).toFixed(1)}s` : it.kind === "sound" ? (st ? "sound" : "·") : it.text}
      </span>,
    );
  }
  return (
    <div className="mx-auto mb-[1.2em] grid max-w-[820px] grid-cols-[52px_minmax(0,1fr)] gap-x-4">
      <span className="pt-[0.55em] text-right font-mono text-[11px] text-muted-foreground tabular-nums">{fmt(items[lo].start).replace(/\.\d$/, "")}</span>
      <p className="font-script text-[19px] leading-[1.8]">{spans}</p>
    </div>
  );
},
(a, b) => a.sig === b.sig && a.showRemoved === b.showRemoved && a.selLo === b.selLo && a.selHi === b.selHi && a.lo === b.lo && a.hi === b.hi);

export default function App() {
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string>("");
  const [sel, setSel] = useState<Sel>(null);
  const [exp, setExp] = useState<ExportState>({ status: "idle" });
  const [format, setFormat] = useState("mp4");
  const [playing, setPlaying] = useState(false);
  const [showRemoved, setShowRemoved] = useState(false);
  const [fixing, setFixing] = useState<{ first: string; last: string; text: string } | null>(null);
  const dragging = useRef(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const clockRef = useRef<HTMLSpanElement>(null);
  const headRef = useRef<HTMLDivElement>(null);
  const stopAt = useRef<number | null>(null);
  const lastTime = useRef(0); // survives a preview source switch, which resets currentTime
  const wasPlaying = useRef(false);
  const projRef = useRef<Project | null>(null);
  projRef.current = project;

  const reload = useCallback(async () => {
    try {
      setProject(await getProject());
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    reload();
    const es = new EventSource("/api/events");
    // reload only for changes made elsewhere (CLI, agent); our own edits already returned the project
    es.onmessage = (e) => {
      if (e.data !== projRef.current?.mtime) reload();
    };
    return () => es.close();
  }, [reload]);

  const states = useMemo(() => (project ? itemStates(project) : []), [project]);
  const paras = useMemo(() => (project ? paragraphs(project.items) : []), [project]);
  const sigs = useMemo(
    () =>
      paras.map(([lo, hi]) => {
        const cuts = states.slice(lo, hi + 1).map((s) => (s ? s.cut.id + s.cut.status[0] + s.cut.nudge.join("/") : "")).join(",");
        const text = project!.items.slice(lo, hi + 1).map((it) => it.text).join(" "); // corrections re-render too
        return `${cuts}|${text}`;
      }),
    [paras, states, project],
  );
  const suggestions = useMemo(() => (project ? project.cuts.filter((c) => c.status === "suggested") : []), [project]);

  const flash = useCallback((msg: string) => {
    toast(msg, { id: "trimscript" }); // one at a time: a new message replaces the last
  }, []);

  const run = useCallback(
    async (body: Record<string, unknown>, done?: string) => {
      try {
        const { project: p, result } = await op(body);
        setProject(p);
        if (done) flash(done.replace("{n}", String(result.suggested ?? result.changed ?? "")));
        return result;
      } catch (e) {
        flash(String(e instanceof Error ? e.message : e));
      }
    },
    [flash],
  );

  // ---------- playback: skip removed ranges, highlight the current word ----------

  useEffect(() => {
    let raf = 0;
    let lastWord = -1;
    const tick = () => {
      const v = videoRef.current;
      const p = projRef.current;
      if (v && p && v.readyState > 0) {
        let t = v.currentTime;
        lastTime.current = t;
        wasPlaying.current = !v.paused;
        if (!v.paused) {
          for (const [lo, hi] of p.removed) {
            if (t >= lo && t < hi - 0.01) {
              v.currentTime = hi;
              t = hi;
              break;
            }
          }
          if (stopAt.current !== null && t >= stopAt.current) {
            v.pause();
            stopAt.current = null;
          }
        }
        if (clockRef.current) {
          clockRef.current.textContent = `${fmt(editedTime(t, p.removed))} / ${fmt(p.kept_duration)}`;
        }
        if (headRef.current) headRef.current.style.width = `${(editedTime(t, p.removed) / Math.max(p.kept_duration, 0.001)) * 100}%`;
        let w = -1;
        let lo = 0;
        let hi = p.items.length - 1;
        while (lo <= hi) {
          const mid = (lo + hi) >> 1;
          if (p.items[mid].start <= t) {
            w = mid;
            lo = mid + 1;
          } else hi = mid - 1;
        }
        if (w !== lastWord) {
          document.querySelector(".tok.now")?.classList.remove("now");
          if (w >= 0 && t <= p.items[w].end + 0.15) {
            const el = document.querySelector(`[data-i="${w}"]:not(.fold)`);
            el?.classList.add("now");
            if (!v.paused && el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
          }
          lastWord = w;
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    // the skip loop runs on animation frames, which stop in a hidden tab; pause rather than
    // let the cut parts play
    const onHide = () => document.hidden && videoRef.current?.pause();
    document.addEventListener("visibilitychange", onHide);
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("visibilitychange", onHide);
    };
  }, []);

  const seek = useCallback((t: number, play = false, until: number | null = null) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = Math.max(0, t);
    stopAt.current = until;
    if (play) v.play();
  }, []);

  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    stopAt.current = null;
    if (v.paused) v.play();
    else v.pause();
  }, []);

  // keep position and play state when the preview switches between original and enhanced voice
  const enhancedSrc = !!project?.settings.enhance && project?.enhance_state.status === "ready";
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const t = lastTime.current;
    const play = wasPlaying.current;
    const restore = () => {
      v.currentTime = t;
      if (play) v.play();
    };
    v.addEventListener("loadedmetadata", restore, { once: true });
    return () => v.removeEventListener("loadedmetadata", restore);
  }, [enhancedSrc]);

  // poll while the preview or the enhanced voice is being built
  const building = project?.enhance_state.status === "running" || project?.preview_state.status === "running";
  useEffect(() => {
    if (!building) return;
    const id = window.setInterval(reload, 1500);
    return () => window.clearInterval(id);
  }, [building, reload]);

  // ---------- selection ----------

  // j: the last index of a folded run, which is selected whole
  const onDown = useCallback((i: number, e: React.MouseEvent, j = i) => {
    e.preventDefault();
    dragging.current = true;
    setSel((s) => (e.shiftKey && s ? { anchor: s.anchor, focus: s.anchor <= i ? j : i } : { anchor: i, focus: j }));
  }, []);
  const onEnter = useCallback((i: number, j = i) => {
    if (dragging.current) setSel((s) => (s ? { anchor: s.anchor, focus: s.anchor <= i ? j : i } : s));
  }, []);
  const onDouble = useCallback(
    (i: number) => {
      const p = projRef.current;
      if (p) seek(p.items[i].start, true);
    },
    [seek],
  );
  useEffect(() => {
    const up = () => (dragging.current = false);
    window.addEventListener("mouseup", up);
    return () => window.removeEventListener("mouseup", up);
  }, []);

  const selLo = sel ? Math.min(sel.anchor, sel.focus) : -1;
  const selHi = sel ? Math.max(sel.anchor, sel.focus) : -1;

  const cutsInSel = useCallback(
    (status?: string) => {
      if (selLo < 0) return [];
      const ids = new Set<string>();
      for (let i = selLo; i <= selHi; i++) {
        const st = states[i];
        if (st && (!status || st.cut.status === status)) ids.add(st.cut.id);
      }
      return [...ids];
    },
    [selLo, selHi, states],
  );

  /** The accepted cut the selection sits on, if exactly one: its edges can be fine-tuned. */
  const focusedCut = useMemo(() => {
    if (selLo < 0) return null;
    const ids = new Set(states.slice(selLo, selHi + 1).map((s) => (s?.cut.status === "accepted" ? s.cut.id : "")));
    if (ids.size !== 1 || ids.has("")) return null;
    return project?.cuts.find((c) => ids.has(c.id)) ?? null;
  }, [selLo, selHi, states, project]);

  const listenAcross = useCallback(
    (cut: Cut) => {
      const p = projRef.current;
      if (!p) return;
      const a = p.items.find((it) => it.id === cut.first)!;
      const b = p.items.find((it) => it.id === cut.last)!;
      seek(a.start - LISTEN_PAD, true, b.end + LISTEN_PAD);
    },
    [seek],
  );

  const nudge = useCallback(
    async (edge: "start" | "end", delta: number) => {
      if (!focusedCut) return;
      await run({ op: "nudge", cut_id: focusedCut.id, edge, delta });
      listenAcross(focusedCut);
    },
    [focusedCut, run, listenAcross],
  );

  const deleteSel = useCallback(() => {
    if (!project || selLo < 0) return;
    const allCut = states.slice(selLo, selHi + 1).every((s) => s?.cut.status === "accepted");
    const first = project.items[selLo].id;
    const last = project.items[selHi].id;
    if (allCut) run({ op: "restore_items", first, last }, "Restored");
    else run({ op: "cut", first, last });
  }, [project, selLo, selHi, states, run]);

  const listen = useCallback(() => {
    if (!project || selLo < 0) return;
    const a = project.items[selLo].start;
    const b = project.items[selHi].end;
    seek(a - LISTEN_PAD, true, b + LISTEN_PAD);
  }, [project, selLo, selHi, seek]);

  /** Tab: step through waiting suggestions, or through the removed parts when none wait, and listen across each. */
  const nextSuggestion = useCallback(
    (dir: 1 | -1) => {
      if (!project) return;
      const pool = suggestions.length ? suggestions : project.cuts.filter((c) => c.status === "accepted");
      if (!pool.length) return;
      const idx = new Map(project.items.map((it, i) => [it.id, i]));
      const spans = pool
        .map((c) => [idx.get(c.first)!, idx.get(c.last)!] as [number, number])
        .sort((x, y) => x[0] - y[0]);
      const from = selLo < 0 ? (dir === 1 ? -1 : Infinity) : selLo;
      const target = dir === 1 ? spans.find((s) => s[0] > from) ?? spans[0] : [...spans].reverse().find((s) => s[0] < from) ?? spans[spans.length - 1];
      setSel({ anchor: target[0], focus: target[1] });
      document.querySelector(`[data-i="${target[0]}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
      const a = project.items[target[0]].start;
      const b = project.items[target[1]].end;
      seek(a - LISTEN_PAD, true, b + LISTEN_PAD);
    },
    [project, suggestions, selLo, seek],
  );

  /** Select and play the next stray sound (voice the transcript has no word for) after the selection. */
  const nextSound = useCallback(() => {
    if (!project) return;
    const from = selLo < 0 ? -1 : selLo;
    const open = project.items.map((it, i) => (it.kind === "sound" && !states[i] ? i : -1)).filter((i) => i >= 0);
    if (!open.length) return flash("No stray sounds left");
    const i = open.find((k) => k > from) ?? open[0];
    setSel({ anchor: i, focus: i });
    document.querySelector(`[data-i="${i}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
    seek(project.items[i].start - LISTEN_PAD, true, project.items[i].end + LISTEN_PAD);
  }, [project, states, selLo, seek, flash]);

  const decide = useCallback(
    async (accept: boolean, all = false) => {
      const ids = all ? null : cutsInSel("suggested");
      if (!all && !ids?.length) return;
      await run({ op: accept ? "accept" : "reject", cut_ids: ids }, `${accept ? "Accepted" : "Rejected"} {n}`);
      if (!all) nextSuggestion(1);
    },
    [cutsInSel, run, nextSuggestion],
  );

  const startFix = useCallback(() => {
    if (!project || selLo < 0) return;
    const words = project.items.slice(selLo, selHi + 1).filter((it) => it.kind === "word" || it.kind === "filler");
    if (!words.length) return;
    setFixing({ first: words[0].id, last: words[words.length - 1].id, text: words.map((w) => w.text).filter(Boolean).join(" ") });
  }, [project, selLo, selHi]);

  const saveFix = useCallback(async () => {
    if (!fixing) return;
    await run({ op: "correct", ...fixing }, "Corrected");
    setFixing(null);
  }, [fixing, run]);

  // ---------- keyboard ----------

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      // menus and fields handle their own keys
      if (e.defaultPrevented || target.closest("input, textarea, select, [role=listbox], [role=menu]")) return;
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        run({ op: e.shiftKey ? "redo" : "undo" });
      } else if (e.key === " ") {
        e.preventDefault();
        togglePlay();
      } else if (e.key === "Backspace" || e.key === "Delete") {
        e.preventDefault();
        deleteSel();
      } else if (e.key === "Tab") {
        e.preventDefault();
        nextSuggestion(e.shiftKey ? -1 : 1);
      } else if (e.key === "Enter") {
        e.preventDefault();
        decide(!e.shiftKey);
      } else if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && focusedCut) {
        e.preventDefault();
        nudge(e.shiftKey ? "end" : "start", e.key === "ArrowLeft" ? -0.01 : 0.01);
      } else if (e.key.toLowerCase() === "e" && !mod) {
        e.preventDefault();
        startFix();
      } else if (e.key.toLowerCase() === "l") {
        listen();
      } else if (e.key === "Escape") {
        setSel(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [run, togglePlay, deleteSel, nextSuggestion, decide, listen, focusedCut, nudge, startFix]);

  // ---------- export ----------

  const doExport = useCallback(async () => {
    try {
      setExp(await startExport(format));
      const poll = window.setInterval(async () => {
        const s = await exportStatus();
        setExp(s);
        if (s.status !== "running") window.clearInterval(poll);
      }, 700);
    } catch (e) {
      flash(String(e instanceof Error ? e.message : e));
    }
  }, [format, flash]);

  if (error) return <Empty>Cannot reach the trimscript server. {error}</Empty>;
  if (!project) return <Empty>Loading…</Empty>;

  const saved = project.duration - project.kept_duration;
  const enhanceOn = !!project.settings.enhance;
  const enhanceReady = enhanceOn && project.enhance_state.status === "ready";
  const previewReady = project.preview_state.status === "ready";
  const src = !previewReady ? undefined : enhanceReady ? "/media/proxy?enhanced=1" : "/media/proxy";
  const selSuggIds = cutsInSel("suggested");
  const selSugg = selSuggIds.length;
  const selCuts = project.cuts.filter((c) => selSuggIds.includes(c.id));

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b bg-card px-5 py-2.5">
        <div className="mr-auto flex min-w-0 items-center gap-3">
          <span className="font-script text-lg font-semibold tracking-tight">
            Trim<span className="text-pencil">Script</span>
          </span>
          <Separator orientation="vertical" className="data-[orientation=vertical]:h-5" />
          <span className="truncate text-sm">{project.name}</span>
          <span className="text-sm whitespace-nowrap text-muted-foreground tabular-nums">
            {fmt(project.duration)} → <b className="font-semibold text-foreground">{fmt(project.kept_duration)}</b>
          </span>
          {saved > 0.05 && (
            <Badge variant="secondary" className="text-ok tabular-nums">
              −{fmt(saved)}
            </Badge>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Tip label="Undo" keys="⌘Z">
            <Button variant="ghost" size="icon-sm" onClick={() => run({ op: "undo" })} disabled={!project.can_undo} aria-label="Undo">
              <Undo2 />
            </Button>
          </Tip>
          <Tip label="Redo" keys="⇧⌘Z">
            <Button variant="ghost" size="icon-sm" onClick={() => run({ op: "redo" })} disabled={!project.can_redo} aria-label="Redo">
              <Redo2 />
            </Button>
          </Tip>
          <Tip label={showRemoved ? "Fold removed parts" : "Show removed text"}>
            <Toggle size="sm" pressed={showRemoved} onPressedChange={setShowRemoved} aria-label="Show removed text">
              {showRemoved ? <Eye /> : <EyeOff />}
            </Toggle>
          </Tip>
          <Separator orientation="vertical" className="mx-1 data-[orientation=vertical]:h-5" />
          <Tip label="Removes every um and uh now. Tab plays across each edit; ⌫ on one brings it back.">
            <Button variant="outline" size="sm" onClick={() => run({ op: "fillers" }, "Removed {n} fillers. Tab to listen through the edits")}>
              <Eraser /> Trim fillers
            </Button>
          </Tip>
          <Tip label="Shortens every pause over 1 s now, keeping a little silence. ⌘Z brings them back.">
            <Button variant="outline" size="sm" onClick={() => run({ op: "pauses" }, "Tightened {n} pauses. ⌘Z brings them back")}>
              <Timer /> Tighten pauses
            </Button>
          </Tip>
          <Tip label="Jumps to the next spot with voice but no word in the transcript and plays it. ⌫ removes it.">
            <Button variant="outline" size="sm" onClick={nextSound}>
              <AudioLines /> Stray sounds
            </Button>
          </Tip>
          <Separator orientation="vertical" className="mx-1 data-[orientation=vertical]:h-5" />
          <Tip label="Noise, level and loudness (-14 LUFS). The length stays the same.">
            <Toggle
              variant="outline"
              size="sm"
              pressed={enhanceOn}
              onPressedChange={(on) => run({ op: "enhance", on }, on ? "Cleaning audio…" : "Original audio")}
              className="data-[state=on]:border-play data-[state=on]:text-play"
            >
              <Sparkles /> {enhanceOn && project.enhance_state.status === "running" ? "Cleaning…" : "Clean audio"}
            </Toggle>
          </Tip>
          <Separator orientation="vertical" className="mx-1 data-[orientation=vertical]:h-5" />
          <Select value={format} onValueChange={setFormat}>
            <SelectTrigger size="sm" className="w-[104px]" aria-label="Export format">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {project.has_video && <SelectItem value="mp4">MP4</SelectItem>}
              <SelectItem value="wav">WAV</SelectItem>
              <SelectItem value="srt">SRT</SelectItem>
              <SelectItem value="vtt">VTT</SelectItem>
              <SelectItem value="fcpxml">FCPXML</SelectItem>
            </SelectContent>
          </Select>
          <Button size="sm" onClick={doExport} disabled={exp.status === "running"}>
            <Download /> {exp.status === "running" ? "Exporting…" : "Export"}
          </Button>
        </div>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[auto_1fr] md:grid-cols-[400px_minmax(0,1fr)] md:grid-rows-1">
        <aside className="bay flex flex-col gap-3 overflow-y-auto bg-background p-5 text-foreground" aria-label="Monitor">
          <div>
            {!previewReady && (
              <p className="pb-2 text-sm text-muted-foreground">
                {project.preview_state.status === "error" ? `Preview failed: ${project.preview_state.error}` : "Preparing preview… you can edit the transcript meanwhile."}
              </p>
            )}
            {project.has_video ? (
              <video
                ref={videoRef}
                src={src}
                preload="auto"
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
                onClick={togglePlay}
                className="block aspect-video w-full rounded-md bg-black ring-1 ring-border"
              />
            ) : (
              <>
                <div className="grid aspect-video place-items-center rounded-md bg-muted text-muted-foreground">
                  <AudioLines className="size-8" />
                </div>
                <video ref={videoRef} src={src} preload="auto" onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} hidden />
              </>
            )}
          </div>
          <div className="flex items-center gap-3">
            <Button size="icon" className="rounded-full bg-play text-background hover:bg-play/90" onClick={togglePlay} aria-label={playing ? "Pause" : "Play"}>
              {playing ? <Pause /> : <Play />}
            </Button>
            <span ref={clockRef} className="font-mono text-sm text-muted-foreground">
              0:00.0
            </span>
          </div>

          {selSugg > 0 && (
            <div className="space-y-2 rounded-md border border-pencil/40 bg-sugg p-3 text-sm">
              {selCuts.slice(0, 3).map((c) => (
                <div key={c.id} className="space-y-1">
                  <Badge variant="outline" className="border-pencil/50 text-pencil">
                    {c.by === "agent" ? <Bot /> : null}
                    {c.by}
                  </Badge>
                  {c.reason && <p className="leading-snug">{c.reason}</p>}
                </div>
              ))}
              {selSugg > 3 && <p className="text-muted-foreground">and {selSugg - 3} more</p>}
              <p className="flex flex-wrap items-center gap-1.5 text-muted-foreground">
                <Kbd>Enter</Kbd> accept <Kbd>⇧Enter</Kbd> reject <Kbd>L</Kbd> listen
              </p>
            </div>
          )}

          <div className="mt-auto hidden space-y-1.5 text-sm text-muted-foreground md:block">
            <p>
              <b className="text-foreground">Select</b> words by dragging. <Kbd>⌫</Kbd> removes them, <Kbd>⌫</Kbd> again restores.
            </p>
            <p>
              <Kbd>Tab</Kbd> steps through the edits and plays across each. <Kbd>L</Kbd> listens across the selection. <Kbd>Space</Kbd> plays the edit.
            </p>
            <p>
              <Kbd>E</Kbd> corrects a misheard word. The video is not touched.
            </p>
            {focusedCut && (
              <p className="text-foreground">
                Removed part selected: <Kbd>←</Kbd> <Kbd>→</Kbd> move its start, <Kbd>⇧←</Kbd> <Kbd>⇧→</Kbd> its end, 10 ms a step.
                {(focusedCut.nudge[0] !== 0 || focusedCut.nudge[1] !== 0) && (
                  <span className="text-muted-foreground tabular-nums">
                    {" "}
                    start {focusedCut.nudge[0] >= 0 ? "+" : ""}
                    {(focusedCut.nudge[0] * 1000).toFixed(0)} ms · end {focusedCut.nudge[1] >= 0 ? "+" : ""}
                    {(focusedCut.nudge[1] * 1000).toFixed(0)} ms
                  </span>
                )}
              </p>
            )}
          </div>

          {exp.status === "done" && <p className="rounded-md border px-3 py-2 text-sm break-all text-ok">Exported to {exp.path}</p>}
          {exp.status === "error" && <p className="rounded-md border px-3 py-2 text-sm break-all text-destructive">{exp.error}</p>}
        </aside>

        <section className="overflow-y-auto px-[clamp(16px,5vw,64px)] pt-8 pb-32 select-none" aria-label="Transcript">
          {paras.map(([lo, hi], k) => {
            const a = selLo > hi || selHi < lo ? -1 : selLo;
            const b = selLo > hi || selHi < lo ? -1 : selHi;
            return (
              <Paragraph
                key={lo}
                lo={lo}
                hi={hi}
                sig={sigs[k]}
                items={project.items}
                states={states}
                removed={project.removed}
                showRemoved={showRemoved}
                selLo={a}
                selHi={b}
                onDown={onDown}
                onEnter={onEnter}
                onDouble={onDouble}
              />
            );
          })}
        </section>
      </main>

      {/* suggestions are reviewed in place, in the transcript and the one monitor, and accepted one
          at a time (or a selected range at a time). Keep it that way: no separate results page or
          list with its own player, and no single control that accepts every suggestion at once. */}
      {suggestions.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 border-t border-pencil/30 bg-sugg px-5 py-2 text-sm">
          <span>
            <strong className="text-pencil">{suggestions.length}</strong> suggestion{suggestions.length > 1 ? "s" : ""} to review
            <span className="text-muted-foreground tabular-nums"> · {fmt(project.kept_if_accepted)} if all accepted</span>
          </span>
          <span className="mr-auto flex items-center gap-1.5 text-muted-foreground">
            <Kbd>Tab</Kbd> next <Kbd>L</Kbd> listen <Kbd>Enter</Kbd> accept <Kbd>⇧Enter</Kbd> reject
          </span>
          <Button size="sm" variant="outline" onClick={() => decide(false, true)}>
            Reject all
          </Button>
        </div>
      )}

      {/* progress through the edit as it will play. Deliberately the edited timeline only: removed
          parts are never drawn as spans on a source timeline or track. */}
      <footer className="bay flex items-center gap-3 bg-background px-5 py-2 text-foreground">
        <span className="font-mono text-[11px] text-muted-foreground">0:00</span>
        <div
          className="relative h-1.5 flex-1 cursor-pointer rounded-full bg-muted"
          aria-label="Progress through the edit"
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            seek(sourceTime(((e.clientX - r.left) / r.width) * project.kept_duration, project.removed));
          }}
        >
          <div ref={headRef} className="absolute inset-y-0 left-0 rounded-full bg-play" />
        </div>
        <span className="font-mono text-[11px] text-muted-foreground">{fmt(project.kept_duration)}</span>
      </footer>

      {fixing && (
        <form
          className="fixed bottom-6 left-1/2 flex w-[min(560px,calc(100vw-32px))] -translate-x-1/2 items-center gap-2.5 rounded-lg border bg-popover px-3.5 py-2.5 text-sm shadow-lg"
          onSubmit={(e) => {
            e.preventDefault();
            saveFix();
          }}
        >
          <label htmlFor="fix" className="shrink-0">
            Correct text
          </label>
          <Input
            id="fix"
            autoFocus
            value={fixing.text}
            onChange={(e) => setFixing({ ...fixing, text: e.target.value })}
            onKeyDown={(e) => e.key === "Escape" && setFixing(null)}
          />
          <Button size="sm" type="submit">
            Save
          </Button>
          <span className="shrink-0 text-muted-foreground">
            <Kbd>Esc</Kbd> cancel
          </span>
        </form>
      )}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="grid h-full place-items-center p-4 text-center text-muted-foreground">{children}</div>;
}

function Tip({ label, keys, children }: { label: string; keys?: string; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent className="max-w-64">
        {label} {keys && <Kbd>{keys}</Kbd>}
      </TooltipContent>
    </Tooltip>
  );
}
