import type { RunState, ScenarioInfo } from "./types";

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export const getScenarios = () => fetch("/api/scenarios").then((r) => json<ScenarioInfo[]>(r));

export const startRun = (body: { scenario_code?: string; scenario?: object; snapshot?: object; overrides?: object }) =>
  fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then((r) => json<{ run_id: string }>(r));

export const getRun = (id: string) => fetch(`/api/runs/${id}`).then((r) => json<RunState>(r));
