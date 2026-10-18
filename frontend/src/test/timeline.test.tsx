// Brief A6: the cooling strip shows a dry share from 0 to 1 per hour.

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Timeline } from '../components/Timeline'
import { createMockClient } from '../mock/client'
import { dryShare } from '../utils/format'

describe('Timeline cooling strip', () => {
  it('dryShare is yd over total and 0 for an idle hour', () => {
    expect(dryShare(10, 0)).toBe(0)
    expect(dryShare(5, 5)).toBe(0.5)
    expect(dryShare(0, 8)).toBe(1)
    expect(dryShare(0, 0)).toBe(0)
  })

  it('renders 24 cooling cells with dry share 0.50 at alpha 0.5', async () => {
    const client = createMockClient(new Date('2026-10-17T12:00:00Z'))
    const [schedule, jobs, signals] = await Promise.all([
      client.optimize({ alpha: 0.5 }),
      client.getJobs(),
      client.getSignals(),
    ])
    render(
      <Timeline
        schedule={schedule}
        jobs={jobs.items}
        signals={signals.items}
        loading={false}
        error={null}
      />,
    )
    const cells = screen.getAllByTestId('cooling-cell')
    expect(cells).toHaveLength(24)
    const busy = cells.filter((c) => c.getAttribute('data-dry-share') !== '0.00')
    expect(busy.length).toBeGreaterThan(0)
    for (const cell of busy) expect(cell.getAttribute('data-dry-share')).toBe('0.50')
  })
})
