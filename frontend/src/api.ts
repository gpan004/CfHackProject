import type { RunState, ScenarioInfo } from "./types";
import type { Brief, RequestCheck, RunStateV2, WhatIfResult } from "./typesV2";

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export const getScenarios = () => fetch("/api/scenarios").then((r) => json<ScenarioInfo[]>(r));

export const startRun = (body: { scenario_code?: string; scenario?: object; snapshot?: object; overrides?: object }) =>
  fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then((r) => json<{ run_id: string }>(r));

export const getRun = (id: string) => fetch(`/api/runs/${id}`).then((r) => json<RunState>(r));

// engine v2 (evidence engine)
export const getStagesV2 = () => fetch("/api/v2/stages").then((r) => json<string[]>(r));
export const startRunV2 = (body: object) =>
  fetch("/api/v2/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then((r) => json<{ run_id: string }>(r));
export const getRunV2 = (id: string) => fetch(`/api/v2/runs/${id}`).then((r) => json<RunStateV2>(r));

const post = <T,>(url: string, body: object) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => json<T>(r));
export const whatIfV2 = (body: object) => post<WhatIfResult>("/api/v2/whatif", body);
export const checkRequestV2 = (body: object) => post<RequestCheck>("/api/v2/check-request", body);
export const rewriteBriefV2 = (runId: string, audience: string, retry = false) =>
  post<{ brief: Brief; audience: string; notes: string[]; stored: boolean }>(`/api/v2/runs/${runId}/brief?audience=${audience}&retry=${retry}`, {});
