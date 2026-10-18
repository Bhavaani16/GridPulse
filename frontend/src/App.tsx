// GridPulse.ai dashboard — single dark page per SPEC 15.
// Data source: VITE_API_URL. When the health check fails (or the env var is
// unset), the whole page falls back to the mock client and shows the banner.

import { useCallback, useEffect, useState } from 'react'
import { createHttpClient, type ApiClient } from './api/client'
import { createMockClient } from './mock/client'
import type {
  ExplainResponse,
  GridSignal,
  Health,
  Job,
  Schedule,
} from './api/types'
import { ActionBar } from './components/ActionBar'
import { AlphaSlider } from './components/AlphaSlider'
import { DecisionFeed } from './components/DecisionFeed'
import { DemoControls } from './components/DemoControls'
import { ExplainCard } from './components/ExplainCard'
import { Header } from './components/Header'
import { KpiCards } from './components/KpiCards'
import { SignalsChart } from './components/SignalsChart'
import { TelemetryChart } from './components/TelemetryChart'
import { Timeline } from './components/Timeline'
import { useDecisionFeed } from './hooks/useDecisionFeed'
import { useTelemetry } from './hooks/useTelemetry'

const DEFAULT_ALPHA = 0.5

// Optional ?alpha=0.75 deep-link sets the first optimize call.
function initialAlpha(): number {
  const raw = new URLSearchParams(window.location.search).get('alpha')
  if (raw === null) return DEFAULT_ALPHA
  const n = Number(raw)
  return Number.isFinite(n) ? Math.min(1, Math.max(0, n)) : DEFAULT_ALPHA
}

const errMsg = (e: unknown) => (e instanceof Error ? e.message : 'request failed')

// Keyed remount clears the hook's seen/lastId state after a demo reset
// (the server deletes every log row, so `after` cursors become stale).
function LiveDecisionFeed({ client }: { client: ApiClient | null }) {
  const { entries, transport, error } = useDecisionFeed(client)
  return <DecisionFeed entries={entries} transport={transport} error={error} />
}

export default function App() {
  const apiBase = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/+$/, '')
  const [client, setClient] = useState<ApiClient | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [unreachable, setUnreachable] = useState(false)

  const [signals, setSignals] = useState<GridSignal[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [signalsError, setSignalsError] = useState<string | null>(null)
  const [jobsError, setJobsError] = useState<string | null>(null)

  const [schedule, setSchedule] = useState<Schedule | null>(null)
  const [alpha, setAlpha] = useState(initialAlpha)
  const [optimizing, setOptimizing] = useState(false)
  const [scheduleError, setScheduleError] = useState<string | null>(null)

  const [explanation, setExplanation] = useState<ExplainResponse | null>(null)
  const [explainLoading, setExplainLoading] = useState(false)
  const [explainError, setExplainError] = useState<string | null>(null)

  const [actionBusy, setActionBusy] = useState(false)
  const [feedNonce, setFeedNonce] = useState(0)

  const refreshStatic = useCallback(async (c: ApiClient) => {
    const [sig, jb] = await Promise.allSettled([c.getSignals(), c.getJobs()])
    if (sig.status === 'fulfilled') {
      setSignals(sig.value.items)
      setSignalsError(null)
    } else {
      setSignalsError(errMsg(sig.reason))
    }
    if (jb.status === 'fulfilled') {
      setJobs(jb.value.items)
      setJobsError(null)
    } else {
      setJobsError(errMsg(jb.reason))
    }
  }, [])

  const runOptimize = useCallback(
    async (a: number, c?: ApiClient) => {
      const cl = c ?? client
      if (!cl) return
      setOptimizing(true)
      setScheduleError(null)
      try {
        const s = await cl.optimize({ alpha: a })
        setSchedule(s)
        setAlpha(s.alpha)
      } catch (e) {
        setScheduleError(errMsg(e))
      } finally {
        setOptimizing(false)
      }
    },
    [client],
  )

  // Connect: health check on VITE_API_URL, fall back to the mock client.
  useEffect(() => {
    let cancelled = false
    const http = apiBase ? createHttpClient(apiBase) : null
    const init = async () => {
      let active: ApiClient
      if (http) {
        try {
          const h = await http.health()
          if (cancelled) return
          setHealth(h)
          active = http
        } catch {
          if (cancelled) return
          setUnreachable(true)
          active = createMockClient()
        }
      } else {
        setUnreachable(true)
        active = createMockClient()
      }
      setClient(active)
      await refreshStatic(active)
      if (cancelled) return
      await runOptimize(initialAlpha(), active)
    }
    void init()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase])

  // Gemini explanation follows the schedule on screen.
  const scheduleId = schedule?.schedule_id
  useEffect(() => {
    if (!client || !scheduleId) return
    let cancelled = false
    setExplainLoading(true)
    setExplainError(null)
    client.explain(scheduleId)
      .then((r) => {
        if (cancelled) return
        setExplanation(r)
        setExplainLoading(false)
      })
      .catch((e) => {
        if (cancelled) return
        setExplanation(null)
        setExplainError(errMsg(e))
        setExplainLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [client, scheduleId])

  const telemetry = useTelemetry(client)

  const act = useCallback(async (fn: (c: ApiClient, id: string) => Promise<Schedule>) => {
    const id = schedule?.schedule_id
    if (!client || !id) return
    setActionBusy(true)
    setScheduleError(null)
    try {
      setSchedule(await fn(client, id))
    } catch (e) {
      setScheduleError(errMsg(e))
    } finally {
      setActionBusy(false)
    }
  }, [client, schedule?.schedule_id])

  const onTriggerSurplus = useCallback(async () => {
    if (!client) return
    setActionBusy(true)
    setScheduleError(null)
    try {
      const s = await client.triggerSurplus()
      setSchedule(s)
      setAlpha(s.alpha)
      const sig = await client.getSignals()
      setSignals(sig.items)
    } catch (e) {
      setScheduleError(errMsg(e))
    } finally {
      setActionBusy(false)
    }
  }, [client])

  const onReset = useCallback(async () => {
    if (!client) return
    setActionBusy(true)
    setScheduleError(null)
    try {
      await client.resetDemo()
      await refreshStatic(client)
      const applied = await client.getAppliedSchedule()
      setSchedule(applied)
      setFeedNonce((n) => n + 1)
    } catch (e) {
      setScheduleError(errMsg(e))
    } finally {
      setActionBusy(false)
    }
  }, [client, refreshStatic])

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-5 lg:px-6">
        <Header health={health} unreachable={unreachable} />

        {unreachable && (
          <div
            role="alert"
            className="rounded-lg border border-amber-700 bg-amber-950/70 px-4 py-2.5 text-sm font-medium text-amber-200"
          >
            Backend unreachable. Showing mock data.
          </div>
        )}

        {schedule ? (
          <KpiCards schedule={schedule} />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-28 animate-pulse rounded-xl border border-slate-800 bg-slate-900/80"
              />
            ))}
          </div>
        )}

        <AlphaSlider
          value={alpha}
          optimizing={optimizing}
          onOptimize={(a) => void runOptimize(a)}
        />

        {scheduleError && (
          <div role="alert" className="rounded-lg border border-rose-800/60 bg-rose-950/50 px-4 py-2.5 text-sm text-rose-300">
            {scheduleError}
          </div>
        )}

        <ExplainCard explanation={explanation} loading={explainLoading} error={explainError} />

        <Timeline
          schedule={schedule}
          jobs={jobs}
          signals={signals}
          loading={!schedule && !scheduleError}
          error={signalsError ?? jobsError}
        />

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <SignalsChart signals={signals} loading={signals.length === 0 && !signalsError} error={signalsError} />
          <TelemetryChart items={telemetry.items} loading={telemetry.loading} error={telemetry.error} />
        </div>

        <LiveDecisionFeed key={feedNonce} client={client} />

        {schedule && (
          <ActionBar
            status={schedule.status}
            scheduleId={schedule.schedule_id}
            busy={actionBusy}
            onRequestApproval={() => void act((c, id) => c.requestApproval(id))}
            onApprove={() => void act((c, id) => c.approve(id))}
            onReject={() => void act((c, id) => c.reject(id))}
          />
        )}

        <DemoControls
          busy={actionBusy}
          onTriggerSurplus={() => void onTriggerSurplus()}
          onReset={() => void onReset()}
        />
      </div>
    </div>
  )
}
