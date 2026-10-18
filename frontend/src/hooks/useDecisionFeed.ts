// Decision log feed per SPEC 15: try GET /api/stream; when the first event
// arrives within 2 s of connecting, keep the SSE stream. Otherwise poll
// GET /api/decisions?after={last_log_id} every 2 s.

import { useEffect, useRef, useState } from 'react'
import type { ApiClient } from '../api/client'
import type { DecisionLogEntry } from '../api/types'

const POLL_MS = 2_000
const SSE_FIRST_EVENT_MS = 2_000
const MAX_ENTRIES = 200

function byTime(a: DecisionLogEntry, b: DecisionLogEntry): number {
  if (a.ts < b.ts) return -1
  if (a.ts > b.ts) return 1
  if (a.log_id < b.log_id) return -1
  if (a.log_id > b.log_id) return 1
  return 0
}

/** Ascending by timestamp. An older page that arrives after a newer one
 * still sorts into place, and the list keeps the newest MAX_ENTRIES. */
export function mergeDecisionEntries(
  prev: DecisionLogEntry[],
  incoming: DecisionLogEntry[],
): DecisionLogEntry[] {
  const seen = new Set(prev.map((entry) => entry.log_id))
  const fresh = incoming.filter((entry) => !seen.has(entry.log_id))
  return [...prev, ...fresh].sort(byTime).slice(-MAX_ENTRIES)
}

export type FeedTransport = 'connecting' | 'sse' | 'poll'

export function useDecisionFeed(client: ApiClient | null): {
  entries: DecisionLogEntry[]
  transport: FeedTransport
  error: string | null
} {
  const [entries, setEntries] = useState<DecisionLogEntry[]>([])
  const [transport, setTransport] = useState<FeedTransport>('connecting')
  const [error, setError] = useState<string | null>(null)
  const seen = useRef(new Set<string>())
  const lastId = useRef<string | null>(null)

  useEffect(() => {
    if (!client) return
    let cancelled = false
    let pollTimer: ReturnType<typeof setInterval> | undefined
    let eventSource: EventSource | undefined

    const append = (items: DecisionLogEntry[]) => {
      const fresh = items.filter((i) => !seen.current.has(i.log_id))
      if (fresh.length === 0) return
      for (const i of fresh) seen.current.add(i.log_id)
      setEntries((prev) => {
        const merged = mergeDecisionEntries(prev, fresh)
        const latest = merged[merged.length - 1]
        if (latest) lastId.current = latest.log_id
        return merged
      })
    }

    const startPolling = () => {
      if (pollTimer) return
      setTransport('poll')
      pollTimer = setInterval(() => {
        client
          .getDecisions({ after: lastId.current ?? undefined })
          .then((r) => {
            if (!cancelled) append(r.items)
          })
          .catch(() => {
            // keep polling; transient failures are not fatal
          })
      }, POLL_MS)
    }

    client
      .getDecisions({ limit: 50 })
      .then((r) => {
        if (cancelled) return
        append(r.items)
        setError(null)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'failed to load decisions')
      })

    const streamUrl = client.streamUrl()
    if (streamUrl && typeof EventSource !== 'undefined') {
      const es = new EventSource(streamUrl)
      eventSource = es
      const deadline = setTimeout(() => {
        es.close()
        startPolling()
      }, SSE_FIRST_EVENT_MS)
      es.addEventListener('decision', (ev) => {
        clearTimeout(deadline)
        setTransport('sse')
        try {
          append([JSON.parse((ev as MessageEvent).data) as DecisionLogEntry])
        } catch {
          // malformed SSE payload; ignore the frame
        }
      })
      es.onerror = () => {
        clearTimeout(deadline)
        es.close()
        startPolling()
      }
    } else {
      startPolling()
    }

    return () => {
      cancelled = true
      eventSource?.close()
      if (pollTimer) clearInterval(pollTimer)
    }
  }, [client])

  return { entries, transport, error }
}
