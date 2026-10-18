import type { Schedule } from '../api/types'
import { fmtLiters, fmtKg, fmtPct, fmtUsd } from '../utils/format'

interface KpiSpec {
  label: string
  unit: string
  pct: number
  deltaText: string
  accent: string
}

export function KpiCards({ schedule }: { schedule: Schedule }) {
  const { metrics, baseline_metrics: base, savings_pct } = schedule
  const kpis: KpiSpec[] = [
    {
      label: 'Cost',
      unit: 'USD',
      pct: savings_pct.cost,
      deltaText: fmtUsd(Math.abs(base.cost_usd - metrics.cost_usd)),
      accent: 'text-amber-300',
    },
    {
      label: 'Carbon',
      unit: 'kg CO2',
      pct: savings_pct.carbon,
      deltaText: fmtKg(Math.abs(base.carbon_kg - metrics.carbon_kg)),
      accent: 'text-emerald-300',
    },
    {
      label: 'Water',
      unit: 'liters',
      pct: savings_pct.water,
      deltaText: fmtLiters(Math.abs(base.water_l - metrics.water_l)),
      accent: 'text-sky-300',
    },
  ]
  return (
    <section aria-label="savings KPIs">
      <div className="mb-2 flex items-center gap-2">
        <span className="rounded border border-amber-600 bg-amber-950/80 px-2 py-0.5 text-xs font-bold uppercase tracking-widest text-amber-300">
          SIMULATED SAVINGS
        </span>
        <span className="text-xs text-slate-500">vs naive baseline · schedule {schedule.schedule_id}</span>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {kpis.map((k) => {
          const positive = k.pct >= 0
          return (
            <div
              key={k.label}
              className="rounded-xl border border-slate-800 bg-slate-900/80 p-4 shadow-lg shadow-black/30"
            >
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                {k.label} <span className="text-slate-500">({k.unit})</span>
              </p>
              <p className={`mt-1 text-3xl font-bold tabular-nums ${k.accent}`}>
                {fmtPct(k.pct)}
              </p>
              <p className="mt-1 text-sm text-slate-400">
                {positive ? 'saved' : 'increased'}{' '}
                <span className="font-semibold text-slate-200">{k.deltaText}</span>
              </p>
            </div>
          )
        })}
      </div>
    </section>
  )
}
