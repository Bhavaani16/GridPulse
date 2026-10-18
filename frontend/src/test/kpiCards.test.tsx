// FE-2 (SPEC 16): KPI text includes the fixture percents and the string
// SIMULATED SAVINGS.

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { KpiCards } from '../components/KpiCards'
import { createMockClient } from '../mock/client'
import { fmtLiters, fmtKg, fmtPct, fmtUsd } from '../utils/format'

describe('KpiCards (FE-2)', () => {
  it('renders fixture savings percents, absolute deltas and SIMULATED SAVINGS', async () => {
    const client = createMockClient(new Date('2026-10-17T12:00:00Z'))
    const schedule = await client.optimize({ alpha: 0.5 })
    render(<KpiCards schedule={schedule} />)

    expect(screen.getByText('SIMULATED SAVINGS')).toBeInTheDocument()

    // percents straight from the fixture schedule
    expect(screen.getByText(fmtPct(schedule.savings_pct.cost))).toBeInTheDocument()
    expect(screen.getByText(fmtPct(schedule.savings_pct.carbon))).toBeInTheDocument()
    expect(screen.getByText(fmtPct(schedule.savings_pct.water))).toBeInTheDocument()

    // absolute deltas: baseline_metrics minus metrics
    expect(
      screen.getByText(
        fmtUsd(Math.abs(schedule.baseline_metrics.cost_usd - schedule.metrics.cost_usd)),
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        fmtKg(Math.abs(schedule.baseline_metrics.carbon_kg - schedule.metrics.carbon_kg)),
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        fmtLiters(Math.abs(schedule.baseline_metrics.water_l - schedule.metrics.water_l)),
      ),
    ).toBeInTheDocument()
  })

  it('says increased and keeps the dollar amount positive when cost is worse', async () => {
    const client = createMockClient(new Date('2026-10-17T12:00:00Z'))
    const schedule = await client.optimize({ alpha: 0.5 })
    const worse = {
      ...schedule,
      metrics: { ...schedule.metrics, cost_usd: schedule.baseline_metrics.cost_usd + 1 },
      savings_pct: { ...schedule.savings_pct, cost: -10 },
    }
    render(<KpiCards schedule={worse} />)
    expect(screen.getByText(/increased/)).toBeInTheDocument()
    expect(screen.getByText('$1.00')).toBeInTheDocument()
    expect(screen.queryByText('$-1.00')).not.toBeInTheDocument()
  })
})
