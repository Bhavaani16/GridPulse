// Polls GET /api/telemetry?minutes=5 for the live telemetry chart.

import { useEffect, useState } from 'react'
import type { ApiClient } from '../api/client'
import type { TelemetryMinute } from '../api/types'

const POLL_MS = 4_000

export function useTelemetry(client: ApiClient | null, minutes = 5): {
  items: TelemetryMinute[]
  loading: boolean
  error: string | null
} {
  const [items, setItems] = useState<TelemetryMinute[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!client) return
    let cancelled = false
    const tick = () => {
      client
        .getTelemetry(minutes)
        .then((r) => {
          if (cancelled) return
          setItems(r.items)
          setLoading(false)
          setError(null)
        })
        .catch((e: unknown) => {
          if (cancelled) return
          setLoading(false)
          setError(e instanceof Error ? e.message : 'failed to load telemetry')
        })
    }
    tick()
    const timer = setInterval(tick, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [client, minutes])

  return { items, loading, error }
}
