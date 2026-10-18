// Collapsed demo panel (SPEC 15): Trigger Surplus and Reset.

export function DemoControls({
  busy,
  onTriggerSurplus,
  onReset,
}: {
  busy: boolean
  onTriggerSurplus: () => void
  onReset: () => void
}) {
  return (
    <details className="rounded-xl border border-slate-800 bg-slate-900/80 shadow-lg shadow-black/30">
      <summary className="cursor-pointer select-none px-4 py-3 text-sm font-semibold uppercase tracking-wider text-slate-400 hover:text-slate-200">
        Demo controls
      </summary>
      <div className="flex flex-wrap items-center gap-3 border-t border-slate-800 px-4 py-3">
        <button
          type="button"
          disabled={busy}
          onClick={onTriggerSurplus}
          className="rounded-lg border border-violet-600 bg-violet-950/60 px-4 py-2 text-sm font-semibold text-violet-200 hover:bg-violet-900/60 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Trigger Surplus
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onReset}
          className="rounded-lg border border-slate-600 bg-slate-800/80 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Reset
        </button>
        <p className="text-xs text-slate-500">
          Surplus re-solves against a temporary 4-hour curtailment boost. The signal chart stays
          on the cached curve. Reset restores the baseline schedule.
        </p>
      </div>
    </details>
  )
}
