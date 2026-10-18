// Mock API client: runs the whole dashboard offline on fixtures.
// Mirrors backend semantics: naive baseline (jobs at release, all-wet cooling),
// a greedy deterministic "optimizer", the approval state machine, a decision
// log, and simulated telemetry. No sockets are opened.

import type { ApiClient } from '../api/client'
import { ApiError } from '../api/client'
import type {
  DecisionLogEntry,
  ExplainResponse,
  GridSignal,
  Job,
  Metrics,
  OptimizeRequest,
  ResetResponse,
  SavingsPct,
  Schedule,
  Slot,
  TelemetryMinute,
} from '../api/types'
import { MOCK_ASSETS, buildJobs, buildSignals, horizonStartUtc } from './fixtures'

const LATENCY_MS = 60
const delay = () => new Promise<void>((resolve) => setTimeout(resolve, LATENCY_MS))

let logCounter = 0
function newLogId(): string {
  logCounter = (logCounter + 1) % 0xffffffffffff
  return `log-${logCounter.toString(16).padStart(12, '0')}`
}

function nowIso(): string {
  return new Date().toISOString()
}

const HOUR_MS = 3_600_000
const slotIndexAt = (signals: { ts: string }[], instant: Date): number => {
  const start = Date.parse(signals[0].ts)
  const i = Math.floor((instant.getTime() - start) / HOUR_MS)
  return i >= 0 && i < signals.length ? i : -1
}

interface Placement {
  [jobId: string]: Record<number, number>
}

function windowOf(job: Job, signals: GridSignal[]): number[] {
  const start = Date.parse(job.release_ts)
  const end = Date.parse(job.deadline_ts)
  const out: number[] = []
  signals.forEach((s, t) => {
    const ts = Date.parse(s.ts)
    if (ts >= start && ts + HOUR_MS <= end) out.push(t)
  })
  return out
}

function naivePlacement(jobs: Job[], signals: GridSignal[]): Placement {
  const placement: Placement = {}
  for (const job of [...jobs].sort((a, b) => a.job_id.localeCompare(b.job_id))) {
    const win = windowOf(job, signals)
    const hours: Record<number, number> = {}
    let remaining = job.duration_h
    for (const t of win) {
      if (remaining <= 1e-8) break
      const f = Math.min(1, remaining)
      hours[t] = f
      remaining -= f
    }
    placement[job.job_id] = hours
  }
  return placement
}

// Greedy deterministic mock "optimizer": moves each job's hours to the cheapest
// (then lowest-carbon) slots inside its window, respecting per-slot capacities.
function optimizedPlacement(
  jobs: Job[],
  signals: GridSignal[],
  itCapKw: number,
  evCapKw: number,
): Placement {
  const ordered = [...jobs].sort((a, b) => a.job_id.localeCompare(b.job_id))
  const itLoad = new Array<number>(signals.length).fill(0)
  const evLoad = new Array<number>(signals.length).fill(0)
  const score = (t: number) =>
    signals[t].price_usd_per_mwh * 10 + signals[t].marginal_gco2_per_kwh / 42
  const placement: Placement = {}

  for (const job of ordered) {
    const win = windowOf(job, signals)
    const isEv = job.asset_id !== 'asset-dc-01'
    const load = isEv ? evLoad : itLoad
    const cap = isEv ? evCapKw : itCapKw
    const fits = (t: number) => load[t] + job.power_kw <= cap + 1e-9
    const byScore = [...win].sort((a, b) => score(a) - score(b) || a - b)
    const hours: Record<number, number> = {}

    if (!job.checkpointable) {
      // cheapest contiguous block of duration_h whole hours
      const len = Math.round(job.duration_h)
      let best: number[] | null = null
      let bestScore = Infinity
      for (let i = 0; i + len <= win.length; i++) {
        const block = win.slice(i, i + len)
        if (block.some((t) => !fits(t))) continue
        const s = block.reduce((acc, t) => acc + score(t), 0)
        if (s < bestScore) {
          bestScore = s
          best = block
        }
      }
      for (const t of best ?? []) hours[t] = 1
    } else {
      let remaining = job.duration_h
      for (const t of byScore) {
        if (remaining <= 1e-8) break
        if (!fits(t)) continue
        const f = Math.min(1, remaining)
        hours[t] = f
        remaining -= f
      }
      if (remaining > 1e-8) {
        // fall back to first-fit in window order
        for (const t of win) {
          if (remaining <= 1e-8) break
          if (hours[t] || !fits(t)) continue
          const f = Math.min(1, remaining)
          hours[t] = f
          remaining -= f
        }
      }
    }
    for (const [t, f] of Object.entries(hours)) load[Number(t)] += job.power_kw * f
    placement[job.job_id] = hours
  }
  return placement
}

function buildSlots(
  signals: GridSignal[],
  jobs: Job[],
  placement: Placement,
  alpha: number,
): Slot[] {
  const jobById = new Map(jobs.map((j) => [j.job_id, j]))
  return signals.map((sig, t) => {
    let it = 0
    let ev = 0
    const slotJobs: { job_id: string; fraction: number }[] = []
    for (const [jobId, hours] of Object.entries(placement)) {
      const f = hours[t] ?? 0
      if (f <= 0) continue
      const job = jobById.get(jobId)
      if (!job) continue
      if (job.asset_id === 'asset-dc-01') it += job.power_kw * f
      else ev += job.power_kw * f
      slotJobs.push({ job_id: jobId, fraction: Math.round(f * 1e6) / 1e6 })
    }
    slotJobs.sort((a, b) => a.job_id.localeCompare(b.job_id))
    const yw = it * (1 - alpha)
    const yd = it * alpha
    const total = it + 0.15 * yw + 0.35 * yd + ev
    return {
      t,
      ts: sig.ts,
      cooling_mode: yd > yw ? 'dry' : 'wet',
      it_load_kw: round6(it),
      yw_kw: round6(yw),
      yd_kw: round6(yd),
      ev_load_kw: round6(ev),
      total_load_kw: round6(total),
      jobs: slotJobs,
    }
  })
}

const round6 = (n: number) => Math.round(n * 1e6) / 1e6

function computeMetrics(signals: GridSignal[], slots: Slot[]): Metrics {
  let cost = 0
  let carbon = 0
  let water = 0
  let energy = 0
  for (const s of slots) {
    const sig = signals[s.t]
    cost += (s.total_load_kw * sig.price_usd_per_mwh) / 1000
    carbon += (s.total_load_kw * sig.marginal_gco2_per_kwh) / 1000
    water += s.yw_kw * 1.8 * sig.water_stress_index
    energy += s.total_load_kw
  }
  return {
    cost_usd: round6(cost),
    carbon_kg: round6(carbon),
    water_l: round6(water),
    energy_kwh: round6(energy),
  }
}

function savingsPct(opt: Metrics, base: Metrics): SavingsPct {
  const pct = (o: number, b: number) => (b === 0 ? 0 : round6(((b - o) / b) * 100))
  return {
    cost: pct(opt.cost_usd, base.cost_usd),
    carbon: pct(opt.carbon_kg, base.carbon_kg),
    water: pct(opt.water_l, base.water_l),
  }
}

function explainText(schedule: Schedule): string {
  const { metrics: m, savings_pct: p } = schedule
  return (
    `Simulated result at alpha ${schedule.alpha.toFixed(2)}: this schedule costs ` +
    `$${m.cost_usd.toFixed(2)}, emits ${m.carbon_kg.toFixed(2)} kg CO2, and uses ` +
    `${m.water_l.toFixed(1)} L of water, which is ${fmtPct(p.cost)} cost, ` +
    `${fmtPct(p.carbon)} carbon, and ${fmtPct(p.water)} water versus the naive ` +
    `baseline. Jobs moved: ${schedule.shifted_job_count}. Cooling follows the ` +
    `wet/dry split in the schedule.`
  )
}

const fmtPct = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`

export function createMockClient(now: Date = new Date()): ApiClient {
  const horizonStart = horizonStartUtc(now)
  let signals = buildSignals(horizonStart)
  const jobs = buildJobs(horizonStart)
  const assets = MOCK_ASSETS
  const itCap = assets[0].it_capacity_kw ?? 20
  const evCap = assets[1].charge_capacity_kw ?? 50

  const logs: DecisionLogEntry[] = []
  const schedules = new Map<string, Schedule>()
  let lastAlpha = 0.5
  let idSuffix = 0

  const writeLog = (
    scheduleId: string | null,
    actor: DecisionLogEntry['actor'],
    event: DecisionLogEntry['event'],
    payload: Record<string, unknown>,
  ) => {
    logs.push({
      log_id: newLogId(),
      ts: nowIso(),
      schedule_id: scheduleId,
      actor,
      event,
      payload,
    })
  }

  const newScheduleId = (alpha: number): string => {
    const stamp = new Date()
      .toISOString()
      .replace(/[-:]/g, '')
      .replace(/\.\d{3}Z$/, 'Z')
    const a = String(Math.round(alpha * 100)).padStart(3, '0')
    const suffix = idSuffix === 0 ? '' : `-${String.fromCharCode(97 + idSuffix)}`
    idSuffix += 1
    return `sch-${stamp}-a${a}${suffix}`
  }

  const baselineSlots = buildSlots(signals, jobs, naivePlacement(jobs, signals), 0)
  const makeBaseline = (): Schedule => {
    const metrics = computeMetrics(signals, baselineSlots)
    const schedule: Schedule = {
      schedule_id: 'sch-baseline',
      schedule_kind: 'baseline',
      status: 'applied',
      alpha: 0.0,
      horizon_start: signals[0].ts,
      created_at: signals[0].ts,
      slots: baselineSlots,
      metrics,
      baseline_metrics: metrics,
      savings_pct: { cost: 0, carbon: 0, water: 0 },
      shifted_job_count: 0,
      shifted_kwh: 0,
      savings_label: 'simulated',
      explanation: null,
    }
    return schedule
  }

  const runOptimize = (alpha: number, kindStatus: 'proposed' = 'proposed'): Schedule => {
    const placement = optimizedPlacement(jobs, signals, itCap, evCap)
    const slots = buildSlots(signals, jobs, placement, alpha)
    const metrics = computeMetrics(signals, slots)
    const baselineMetrics = computeMetrics(signals, baselineSlots)
    const naive = naivePlacement(jobs, signals)
    let shifted = 0
    let shiftedKwh = 0
    for (const job of jobs) {
      const diff = signals.some(
        (_s, t) => Math.abs((placement[job.job_id]?.[t] ?? 0) - (naive[job.job_id]?.[t] ?? 0)) > 1e-6,
      )
      if (diff) {
        shifted += 1
        shiftedKwh += job.energy_kwh
      }
    }
    const schedule: Schedule = {
      schedule_id: newScheduleId(alpha),
      schedule_kind: 'optimized',
      status: kindStatus,
      alpha,
      horizon_start: signals[0].ts,
      created_at: nowIso(),
      slots,
      metrics,
      baseline_metrics: baselineMetrics,
      savings_pct: savingsPct(metrics, baselineMetrics),
      shifted_job_count: shifted,
      shifted_kwh: round6(shiftedKwh),
      savings_label: 'simulated',
      explanation: null,
    }
    schedules.set(schedule.schedule_id, schedule)
    writeLog(schedule.schedule_id, 'optimizer', 'proposed', {
      alpha,
      shifted_job_count: shifted,
      shifted_kwh: schedule.shifted_kwh,
    })
    return schedule
  }

  schedules.set('sch-baseline', makeBaseline())
  writeLog(null, 'system', 'startup', { mode: 'cached', hardware_mode: 'simulated' })
  runOptimize(lastAlpha)

  const getScheduleOr404 = (id: string): Schedule => {
    const s = schedules.get(id)
    if (!s) throw new ApiError(404, 'not_found', `unknown schedule_id ${id}`)
    return s
  }

  const setStatus = (id: string, status: Schedule['status']) => {
    const s = getScheduleOr404(id)
    const updated = { ...s, status }
    schedules.set(id, updated)
    return updated
  }

  const requestApproval = (id: string): Schedule => {
    const s = getScheduleOr404(id)
    if (s.status !== 'proposed') {
      throw new ApiError(409, 'invalid_state', `cannot request approval for a schedule in status ${s.status}`, {
        schedule_id: id,
        status: s.status,
      })
    }
    const updated = setStatus(id, 'pending_approval')
    writeLog(id, 'dashboard', 'approval_requested', {
      shifted_job_count: s.shifted_job_count,
      shifted_kwh: s.shifted_kwh,
    })
    writeLog(id, 'photon', 'sms_sent', {
      message_id: `mock-sms-${id}`,
      phone_masked: '********00',
      text: `GridPulse schedule ${id}: reply YES to apply, NO to reject`,
    })
    return updated
  }

  const approve = (id: string): Schedule => {
    const s = getScheduleOr404(id)
    if (s.status !== 'proposed' && s.status !== 'pending_approval') {
      throw new ApiError(409, 'invalid_state', `cannot approve a schedule in status ${s.status}`, {
        schedule_id: id,
        status: s.status,
      })
    }
    const previous = [...schedules.values()].find((x) => x.status === 'applied')
    setStatus(id, 'approved')
    writeLog(id, 'dashboard', 'approved', { via: 'dashboard' })
    if (previous) {
      schedules.set(previous.schedule_id, { ...previous, status: 'superseded' })
      writeLog(previous.schedule_id, 'system', 'superseded', { replaced_by: id })
    }
    const applied = setStatus(id, 'applied')
    writeLog(id, 'system', 'applied', { previous_schedule_id: previous?.schedule_id ?? '' })
    const signature = `mocksig-${id.replace(/[^a-f0-9]/gi, '0').slice(0, 16).padEnd(16, '0')}`
    writeLog(id, 'solana', 'settlement_tx', {
      signature,
      explorer_url: null,
      mode: 'mock',
    })
    return applied
  }

  const reject = (id: string): Schedule => {
    const s = getScheduleOr404(id)
    if (s.status !== 'proposed' && s.status !== 'pending_approval') {
      throw new ApiError(409, 'invalid_state', `cannot reject a schedule in status ${s.status}`, {
        schedule_id: id,
        status: s.status,
      })
    }
    writeLog(id, 'dashboard', 'rejected', { reason: 'dashboard' })
    return setStatus(id, 'rejected')
  }

  const telemetryMinutes = (minutes: number): TelemetryMinute[] => {
    const applied = [...schedules.values()].find((s) => s.status === 'applied')
    const currentSlot = applied ? slotIndexAt(applied.slots, new Date()) : -1
    const fanOn =
      currentSlot >= 0 && applied ? applied.slots[currentSlot].cooling_mode === 'wet' : true
    const now = Date.now()
    const items: TelemetryMinute[] = []
    for (let i = minutes - 1; i >= 0; i--) {
      const bucketStart = new Date(Math.floor(now / 60000) * 60000 - i * 60000)
      const phase = Math.sin((bucketStart.getTime() / 60000) * 0.9)
      items.push({
        bucket: bucketStart.toISOString().replace(/\.\d{3}Z$/, 'Z'),
        device_id: 'esp32-fan-sim',
        power_w: round6(fanOn ? 4.5 + phase * 0.4 : 0.3 + Math.abs(phase) * 0.1),
        temp_c: round6(30 + phase * 1.5),
        fan_on: fanOn,
        simulated: true,
      })
    }
    return items
  }

  const resetDemo = (): ResetResponse => {
    signals = buildSignals(horizonStart)
    logs.length = 0
    schedules.clear()
    idSuffix = 0
    schedules.set('sch-baseline', makeBaseline())
    writeLog(null, 'system', 'reset', { applied_schedule_id: 'sch-baseline' })
    return { status: 'ok', applied_schedule_id: 'sch-baseline' }
  }

  const triggerSurplus = (): Schedule => {
    const t0 = slotIndexAt(signals, new Date())
    const start = t0 >= 0 ? t0 : 10
    signals = signals.map((s, t) =>
      t >= start && t <= start + 3 && t <= 23
        ? {
            ...s,
            curtailment_mw: s.curtailment_mw + 300,
            price_usd_per_mwh: s.price_usd_per_mwh * 0.5,
            marginal_gco2_per_kwh: s.marginal_gco2_per_kwh * 0.5,
          }
        : s,
    )
    const schedule = runOptimize(lastAlpha)
    if (schedule.shifted_job_count > 0) {
      return { ...requestApproval(schedule.schedule_id) }
    }
    return approve(schedule.schedule_id)
  }

  return {
    health: async () => {
      await delay()
      return {
        status: 'ok',
        mode: 'cached',
        hardware_mode: 'simulated',
        database: 'sqlite',
        optimizer_mode: 'real',
        photon_mode: 'mock',
        gemini_mode: 'mock',
        solana_mode: 'mock',
        agents_mode: 'local',
      }
    },
    getSignals: async () => {
      await delay()
      return { horizon_start: signals[0].ts, items: signals }
    },
    getJobs: async () => {
      await delay()
      return { items: jobs }
    },
    getAssets: async () => {
      await delay()
      return { items: assets }
    },
    optimize: async (req: OptimizeRequest) => {
      await delay()
      lastAlpha = req.alpha
      return runOptimize(req.alpha)
    },
    getAppliedSchedule: async () => {
      await delay()
      const s = [...schedules.values()].find((x) => x.status === 'applied')
      if (!s) throw new ApiError(404, 'not_found', 'no applied schedule')
      return s
    },
    getSchedule: async (id) => {
      await delay()
      return getScheduleOr404(id)
    },
    requestApproval: async (id) => {
      await delay()
      return requestApproval(id)
    },
    approve: async (id) => {
      await delay()
      return approve(id)
    },
    reject: async (id) => {
      await delay()
      return reject(id)
    },
    explain: async (id): Promise<ExplainResponse> => {
      await delay()
      const s = getScheduleOr404(id)
      const text = explainText(s)
      writeLog(id, 'gemini', 'explanation', { source: 'fallback', text })
      return { schedule_id: id, text, source: 'fallback' }
    },
    getDecisions: async ({ limit = 50, after } = {}) => {
      await delay()
      let items = logs
      if (after) {
        const idx = logs.findIndex((l) => l.log_id === after)
        items = idx >= 0 ? logs.slice(idx + 1) : []
      }
      return { items: items.slice(0, limit) }
    },
    getTelemetry: async (minutes = 5) => {
      await delay()
      return { items: telemetryMinutes(minutes) }
    },
    triggerSurplus: async () => {
      await delay()
      return triggerSurplus()
    },
    resetDemo: async () => {
      await delay()
      return resetDemo()
    },
    streamUrl: () => null,
  }
}
