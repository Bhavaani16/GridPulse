import { render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../api/client'
import type { Schedule } from '../api/types'
import { usePendingSchedule } from '../hooks/usePendingSchedule'

function pending(): Schedule {
  return {
    schedule_id: 'sch-pending',
    schedule_kind: 'optimized',
    status: 'pending_approval',
    alpha: 0.5,
    horizon_start: '2026-10-18T07:00:00Z',
    created_at: '2026-10-18T17:00:00.000Z',
    slots: [],
    metrics: { cost_usd: 1, carbon_kg: 1, water_l: 0, energy_kwh: 1 },
    baseline_metrics: { cost_usd: 2, carbon_kg: 2, water_l: 2, energy_kwh: 2 },
    savings_pct: { cost: 50, carbon: 50, water: 100 },
    shifted_job_count: 1,
    shifted_kwh: 1,
    savings_label: 'simulated',
    explanation: null,
  }
}

function Harness({ client }: { client: ApiClient }) {
  const [schedule, setSchedule] = useState(pending)
  usePendingSchedule(client, schedule, setSchedule)
  return <span data-testid="status">{schedule.status}</span>
}

describe('usePendingSchedule', () => {
  it('replaces a pending schedule when the server has applied it', async () => {
    const applied = { ...pending(), status: 'applied' as const }
    const getSchedule = vi.fn().mockResolvedValue(applied)
    const client = { getSchedule } as unknown as ApiClient

    render(<Harness client={client} />)
    expect(await screen.findByText('applied')).toBeInTheDocument()
    expect(getSchedule).toHaveBeenCalledWith('sch-pending')
  })
})
