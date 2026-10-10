export type Kind = "word" | "filler" | "sound" | "pause";

export interface Item {
  id: string;
  text: string;
  start: number;
  end: number;
  kind: Kind;
}

export interface Cut {
  id: string;
  first: string;
  last: string;
  status: "accepted" | "suggested";
  by: string;
  reason: string;
  nudge: [number, number];
}

export interface Project {
  name: string;
  source: string;
  duration: number;
  has_video: boolean;
  items: Item[];
  cuts: Cut[];
  removed: [number, number][];
  kept_duration: number;
  kept_if_accepted: number;
  rev: number;
  settings: { enhance?: boolean };
  preview_state: { status: "running" | "ready" | "error"; error?: string };
  enhance_state: { status: "idle" | "running" | "ready" | "error"; error?: string };
  mtime: string;
  can_undo: boolean;
  can_redo: boolean;
}

export interface ExportState {
  status: "idle" | "running" | "done" | "error";
  path?: string;
  error?: string;
}

export async function getProject(): Promise<Project> {
  const r = await fetch("/api/project");
  if (!r.ok) throw new Error(`load failed: ${r.status}`);
  return r.json();
}

/** Apply an edit. The server answers with the updated project, so no second fetch is needed. */
export async function op(body: Record<string, unknown>): Promise<{ project: Project; result: Record<string, unknown> }> {
  const r = await fetch("/api/ops", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `edit failed: ${r.status}`);
  const result = JSON.parse(r.headers.get("X-TrimScript-Result") ?? "{}");
  return { project: await r.json(), result };
}

export async function startExport(format: string): Promise<ExportState> {
  const r = await fetch("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ format }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? "export failed");
  return r.json();
}

export async function exportStatus(): Promise<ExportState> {
  return (await fetch("/api/export")).json();
}
