import type { Health } from '../api/types'

function Badge({ label, tone }: { label: string; tone: 'sky' | 'amber' | 'emerald' | 'slate' }) {
  const tones: Record<string, string> = {
    sky: 'border-sky-700 bg-sky-950/70 text-sky-300',
    amber: 'border-amber-700 bg-amber-950/70 text-amber-300',
    emerald: 'border-emerald-700 bg-emerald-950/70 text-emerald-300',
    slate: 'border-slate-700 bg-slate-900 text-slate-300',
  }
  return (
    <span
      className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${tones[tone]}`}
    >
      {label}
    </span>
  )
}

export function Header({ health, unreachable }: { health: Health | null; unreachable: boolean }) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-50">GridPulse.ai</h1>
        <p className="text-sm text-slate-400">Campus scheduler — cost, carbon, water</p>
      </div>
      <div className="flex items-center gap-2" aria-label="backend status">
        {unreachable ? (
          <Badge label="offline mock" tone="amber" />
        ) : health ? (
          <>
            <Badge label={`mode ${health.mode}`} tone={health.mode === 'live' ? 'emerald' : 'sky'} />
            <Badge
              label={`hardware ${health.hardware_mode}`}
              tone={health.hardware_mode === 'real' ? 'emerald' : 'slate'}
            />
            <Badge label={`db ${health.database}`} tone="slate" />
          </>
        ) : (
          <Badge label="connecting" tone="slate" />
        )}
      </div>
    </header>
  )
}
