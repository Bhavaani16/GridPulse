// Decision log feed (SPEC 15): ascending time, actor icon + name, event name,
// relative timestamp. settlement_tx entries link to the Solana explorer.

import { useEffect, useRef, useState } from 'react'
import type { DecisionLogEntry } from '../api/types'
import { relTime } from '../utils/format'
import { Panel } from './Panel'

const ACTOR_STYLE: Record<string, string> = {
  system: 'bg-slate-600',
  optimizer: 'bg-emerald-600',
  dashboard: 'bg-sky-600',
  photon: 'bg-amber-600',
  gemini: 'bg-violet-600',
  solana: 'bg-fuchsia-600',
  'grid-agent': 'bg-teal-600',
  'dc-agent': 'bg-teal-600',
  'ev-agent': 'bg-teal-600',
  bridge: 'bg-teal-600',
  simulator: 'bg-rose-600',
}

const EXPLORER_BASE = 'https://explorer.solana.com/tx/'

function settlementUrl(entry: DecisionLogEntry): string | null {
  const url = entry.payload.explorer_url
  if (typeof url === 'string') return url
  const sig = entry.payload.signature
  if (typeof sig === 'string' && sig.length > 0) return `${EXPLORER_BASE}${sig}?cluster=devnet`
  return null
}

function payloadSummary(entry: DecisionLogEntry): string {
  const p = entry.payload
  const parts: string[] = []
  for (const key of ['alpha', 'via', 'reason', 'mode', 'source', 'integration', 'shifted_job_count']) {
    const v = p[key]
    if (typeof v === 'number' || typeof v === 'string') parts.push(`${key}=${v}`)
  }
  return parts.join('  ')
}

function Row({ entry, now }: { entry: DecisionLogEntry; now: number }) {
  const url = entry.event === 'settlement_tx' ? settlementUrl(entry) : null
  const summary = payloadSummary(entry)
  return (
    <li className="flex items-start gap-2.5 py-1.5">
      <span
        className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold uppercase text-white ${ACTOR_STYLE[entry.actor] ?? 'bg-slate-600'}`}
        aria-hidden
      >
        {entry.actor.slice(0, 2)}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm">
          <span className="font-medium text-slate-200">{entry.actor}</span>{' '}
          <span className="text-slate-400">{entry.event}</span>
          {entry.schedule_id && (
            <span className="ml-1 text-xs text-slate-500">{entry.schedule_id}</span>
          )}
        </p>
        {summary && <p className="truncate text-xs text-slate-500">{summary}</p>}
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-fuchsia-400 underline decoration-fuchsia-700 hover:text-fuchsia-300"
          >
            view on Solana explorer (devnet)
          </a>
        )}
      </div>
      <time className="shrink-0 text-xs tabular-nums text-slate-500" dateTime={entry.ts}>
        {relTime(entry.ts, now)}
      </time>
    </li>
  )
}

export function DecisionFeed({
  entries,
  transport,
  error,
}: {
  entries: DecisionLogEntry[]
  transport: 'connecting' | 'sse' | 'poll'
  error: string | null
}) {
  const [now, setNow] = useState(() => Date.now())
  const listRef = useRef<HTMLUListElement>(null)

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 15_000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [entries.length])

  return (
    <Panel
      title="Decision log"
      error={error}
      right={
        <span className="rounded border border-slate-700 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">
          {transport === 'sse' ? 'live stream' : transport === 'poll' ? 'polling 2s' : 'connecting'}
        </span>
      }
    >
      <ul ref={listRef} className="max-h-72 divide-y divide-slate-800/70 overflow-y-auto pr-1" aria-label="decision log">
        {entries.length === 0 ? (
          <li className="py-3 text-sm text-slate-500">No decisions yet.</li>
        ) : (
          entries.map((e) => <Row key={e.log_id} entry={e} now={now} />)
        )}
      </ul>
    </Panel>
  )
}
