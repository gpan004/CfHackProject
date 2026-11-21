import { useEffect, useRef, useState } from "react";
import { getRun, getScenarios, startRun } from "./api";
import type { RunState, ScenarioInfo } from "./types";
import RunPanel from "./components/RunPanel";
import StrategyView from "./components/StrategyView";

export default function App() {
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([]);
  const [run, setRun] = useState<RunState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number>();

  useEffect(() => {
    getScenarios().then(setScenarios).catch((e) => setError(String(e)));
    return () => window.clearInterval(timer.current);
  }, []);

  const launch = async (body: object) => {
    setError(null);
    window.clearInterval(timer.current);
    try {
      const { run_id } = await startRun(body);
      setRun({ run_id, status: "queued", stage: null, stages_done: [], error: null, result: null });
      timer.current = window.setInterval(async () => {
        try {
          const s = await getRun(run_id);
          setRun(s);
          if (s.status === "done" || s.status === "error") window.clearInterval(timer.current);
        } catch (e) {
          setError(String(e));
          window.clearInterval(timer.current);
        }
      }, 2000);
    } catch (e) {
      setError(String(e));
    }
  };

  const busy = run?.status === "queued" || run?.status === "running";

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1240px] items-center justify-between px-6 py-5">
          <div className="flex items-baseline gap-3">
            <span className="font-display text-[34px] font-semibold leading-none tracking-tight">Ingaze</span>
            <span className="hidden text-sm text-slate-500 sm:inline">Action Recommendation Engine</span>
          </div>
          <nav className="hidden items-center gap-8 text-[16px] font-medium md:flex">
            <a href="#strategy" className="hover:text-brand">Strategy</a>
            <a href="#evidence" className="hover:text-brand">Evidence</a>
            <a href="#roi" className="hover:text-brand">ROI</a>
            <a href="#charts" className="hover:text-brand">Analytics</a>
          </nav>
          <a href="#run" className="btn px-6 py-3">Run analysis</a>
        </div>
      </header>

      <section className="mx-auto max-w-[1240px] px-6 pb-10 pt-14">
        <h1 className="max-w-3xl text-[44px] font-extrabold leading-[1.05] md:text-[48px]">
          From employee-experience data<br />
          <span className="text-brand">to a board-ready action plan.</span>
        </h1>
        <p className="mt-6 max-w-2xl text-[16px] leading-relaxed text-ink/80">
          A diagnosis across employer branding, recruiting, advocacy and retention. Root causes are separated from symptoms,
          matched against precedent case studies, guardrailed by HR rules and priced with an auditable ROI.
        </p>
      </section>

      <main className="mx-auto grid max-w-[1240px] gap-8 px-6 pb-24 lg:grid-cols-[320px_1fr]">
        <aside id="run" className="lg:sticky lg:top-28 lg:self-start">
          <RunPanel scenarios={scenarios} run={run} busy={busy} onRun={launch} />
          {error && <p className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        </aside>
        <div className="min-w-0">
          {run?.status === "error" && (
            <div className="card border-red-200 bg-red-50 text-red-700"><b>Run failed.</b> {run.error}</div>
          )}
          {run?.result ? (
            <StrategyView r={run.result} runId={run.run_id} />
          ) : (
            run?.status !== "error" && (
              <div className="card flex min-h-[420px] flex-col items-center justify-center text-center">
                <p className="eyebrow">{busy ? "Analysis in progress" : "Ready"}</p>
                <h2 className="mt-3 text-2xl font-bold">{busy ? "Building the strategy…" : "Choose a company and run the engine."}</h2>
                <p className="mt-2 max-w-md text-ink/70">
                  {busy ? `Current stage: ${run?.stage ?? "queued"}` : "The winning plan, its evidence, the jury verdict and the ROI appear here."}
                </p>
              </div>
            )
          )}
        </div>
      </main>
    </div>
  );
}
