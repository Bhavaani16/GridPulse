// A Photon YES applies the schedule on the server. The dashboard does not
// send that request, so the status chip has to re-read a pending row.

import { useEffect } from 'react'
import type { ApiClient } from '../api/client'
import type { Schedule } from '../api/types'

const POLL_MS = 2_000

export function usePendingSchedule(
  client: ApiClient | null,
  schedule: Schedule | null,
  onSchedule: (next: Schedule) => void,
): void {
  const scheduleId = schedule?.schedule_id
  const status = schedule?.status

  useEffect(() => {
    if (!client || !scheduleId || status !== 'pending_approval') return
    let cancelled = false
    const tick = () => {
      client
        .getSchedule(scheduleId)
        .then((next) => {
          if (!cancelled && next.status !== 'pending_approval') onSchedule(next)
        })
        .catch(() => {
          // The next tick retries. A missed poll must not blank the page.
        })
    }
    tick()
    const timer = setInterval(tick, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [client, scheduleId, status, onSchedule])
}
