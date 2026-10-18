// 24-hour schedule timeline (SPEC 15): one row per job that runs, blocks where
// it runs, a cooling-mode strip per hour, a curtailment marker strip, and a
// faint overlay on curtailed hours.

import type { GridSignal, Job, Schedule } from '../api/types'
import { hourLabel } from '../utils/format'
import { Panel } from './Panel'

const CURTAILMENT_THRESHOLD_MW = 50

const LABEL_COL = 'minmax(10rem,12rem)'

interface JobRow {
  job: Job
  fractions: number[] // index by slot t
}

function jobRows(schedule: Schedule, jobs: Job[]): JobRow[] {
  const byId = new Map(jobs.map((j) => [j.job_id, j]))
  const rows: JobRow[] = []
  for (const slot of schedule.slots) {
    for (const sj of slot.jobs) {
      const job = byId.get(sj.job_id)
      if (!job) continue
      let row = rows.find((r) => r.job.job_id === sj.job_id)
      if (!row) {
        row = { job, fractions: new Array(24).fill(0) }
        rows.push(row)
      }
      row.fractions[slot.t] = sj.fraction
    }
  }
  return rows.sort((a, b) => a.job.job_id.localeCompare(b.job.job_id))
}

const JOB_FILL: Record<Job['kind'], string> = {
  compute: 'bg-emerald-500',
  ev_charge: 'bg-sky-500',
}

export function Timeline({
  schedule,
  jobs,
  signals,
  loading,
  error,
}: {
  schedule: Schedule | null
  jobs: Job[]
  signals: GridSignal[]
  loading: boolean
  error: string | null
}) {
  const curtailed = new Set(
    signals.flatMap((s, t) => (s.curtailment_mw >= CURTAILMENT_THRESHOLD_MW ? [t] : [])),
  )
  const rows = schedule ? jobRows(schedule, jobs) : []
  const colTemplate = `${LABEL_COL} repeat(24, minmax(0,1fr))`

  return (
    <Panel title="24-hour schedule" loading={loading} error={error}>
      {schedule && (
        <div className="overflow-x-auto">
          <div className="min-w-[720px]">
            {/* hour header */}
            <div className="grid gap-px" style={{ gridTemplateColumns: colTemplate }}>
              <div />
              {schedule.slots.map((s) => (
                <div
                  key={s.t}
                  className={`pb-1 text-center text-[10px] tabular-nums ${
                    curtailed.has(s.t) ? 'font-semibold text-violet-300' : 'text-slate-500'
                  }`}
                >
                  {hourLabel(s.ts).slice(0, 2)}
                </div>
              ))}
            </div>

            {/* job rows */}
            {rows.map(({ job, fractions }) => (
              <div
                key={job.job_id}
                className="grid items-center gap-px"
                style={{ gridTemplateColumns: colTemplate }}
              >
                <div className="truncate pr-2 py-1 text-xs text-slate-300" title={`${job.job_id} — ${job.name}`}>
                  <span className="mr-1 inline-block w-[4.7rem] text-slate-500">{job.job_id}</span>
                  {job.name}
                  {!job.checkpointable && (
                    <span className="ml-1 text-[10px] uppercase text-amber-400">ncp</span>
                  )}
                </div>
                {fractions.map((f, t) => (
                  <div
                    key={t}
                    className={`relative h-6 rounded-sm ${
                      curtailed.has(t) ? 'bg-violet-500/15' : 'bg-slate-800/60'
                    }`}
                    title={
                      f > 0
                        ? `${job.name} · slot ${t} · fraction ${f}`
                        : `slot ${t}`
                    }
                  >
                    {f > 0 && (
                      <div
                        className={`absolute inset-0 rounded-sm ${JOB_FILL[job.kind]}`}
                        style={{ opacity: 0.35 + 0.65 * Math.min(1, f) }}
                      />
                    )}
                  </div>
                ))}
              </div>
            ))}

            {/* cooling mode strip */}
            <div
              className="mt-2 grid items-center gap-px"
              style={{ gridTemplateColumns: colTemplate }}
            >
              <div className="py-0.5 pr-2 text-xs text-slate-400">cooling</div>
              {schedule.slots.map((s) => (
                <div
                  key={s.t}
                  className={`flex h-4 items-center justify-center rounded-sm text-[9px] font-bold uppercase ${
                    s.cooling_mode === 'wet'
                      ? 'bg-sky-700/80 text-sky-100'
                      : 'bg-amber-700/80 text-amber-100'
                  } ${curtailed.has(s.t) ? 'ring-1 ring-violet-400/40' : ''}`}
                  title={`slot ${s.t}: ${s.cooling_mode} cooling (yw ${s.yw_kw} kW, yd ${s.yd_kw} kW)`}
                >
                  {s.cooling_mode === 'wet' ? 'w' : 'd'}
                </div>
              ))}
            </div>

            {/* curtailment marker strip */}
            <div
              className="mt-1 grid items-center gap-px"
              style={{ gridTemplateColumns: colTemplate }}
            >
              <div className="py-0.5 pr-2 text-xs text-slate-400">curtailment</div>
              {signals.map((s, t) => (
                <div key={t} className="flex h-4 items-center justify-center">
                  {s.curtailment_mw >= CURTAILMENT_THRESHOLD_MW && (
                    <div
                      className="h-2.5 w-2.5 rotate-45 rounded-[2px] bg-violet-400"
                      title={`slot ${t}: curtailment ${s.curtailment_mw} MW`}
                    />
                  )}
                </div>
              ))}
            </div>

            {/* legend */}
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-400">
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm bg-emerald-500" /> compute job
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm bg-sky-500" /> EV charge
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm bg-sky-700" /> wet cooling
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm bg-amber-700" /> dry cooling
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rotate-45 rounded-[2px] bg-violet-400" /> curtailment ≥{' '}
                {CURTAILMENT_THRESHOLD_MW} MW
              </span>
              <span className="text-slate-500">ncp = non-checkpointable</span>
            </div>
          </div>
        </div>
      )}
    </Panel>
  )
}
