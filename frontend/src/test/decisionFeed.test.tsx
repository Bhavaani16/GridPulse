// FE-3 (SPEC 16): a new decision-log entry appears in the feed.
// Drives the real useDecisionFeed hook with a stubbed client (no SSE, so it
// falls back to polling GET /api/decisions?after=... every 2 s).

import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../api/client'
import type { DecisionLogEntry } from '../api/types'
import { DecisionFeed } from '../components/DecisionFeed'
import { mergeDecisionEntries, useDecisionFeed } from '../hooks/useDecisionFeed'

function entry(logId: string, event: DecisionLogEntry['event'], ts: string): DecisionLogEntry {
  return {
    log_id: logId,
    ts,
    schedule_id: 'sch-test',
    actor: 'optimizer',
    event,
    payload: {},
  }
}

function FeedHarness({ client }: { client: ApiClient }) {
  const { entries, transport } = useDecisionFeed(client)
  return (
    <div>
      <span data-testid="transport">{transport}</span>
      <DecisionFeed entries={entries} transport={transport} error={null} />
    </div>
  )
}

describe('mergeDecisionEntries', () => {
  it('sorts an older page that arrives after a newer batch', () => {
    const newer = entry('log-new', 'applied', '2026-10-17T12:00:05.000Z')
    const older = entry('log-old', 'startup', '2026-10-17T12:00:00.000Z')
    const merged = mergeDecisionEntries([newer], [older])
    expect(merged.map((row) => row.log_id)).toEqual(['log-old', 'log-new'])
  })
})

describe('DecisionFeed (FE-3)', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders initial entries and picks up new ones on the next poll', async () => {
    vi.useFakeTimers()
    const first = entry('log-000000000001', 'proposed', '2026-10-17T12:00:00.000Z')
    const second = entry('log-000000000002', 'approved', '2026-10-17T12:00:02.000Z')
    const getDecisions = vi
      .fn()
      .mockResolvedValueOnce({ items: [first] })
      .mockResolvedValue({ items: [second] })
    const client = { getDecisions, streamUrl: () => null } as unknown as ApiClient

    render(<FeedHarness client={client} />)

    await act(async () => {
      await Promise.resolve()
    })
    expect(screen.getByText('proposed')).toBeInTheDocument()
    expect(screen.queryByText('approved')).not.toBeInTheDocument()

    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })

    expect(screen.getByText('approved')).toBeInTheDocument()
    expect(getDecisions).toHaveBeenCalledWith({ after: 'log-000000000001' })
    expect(screen.getByTestId('transport')).toHaveTextContent('poll')
  })

  it('links settlement_tx entries to the Solana devnet explorer', () => {
    const tx: DecisionLogEntry = {
      log_id: 'log-000000000003',
      ts: '2026-10-17T12:00:00.000Z',
      schedule_id: 'sch-test',
      actor: 'solana',
      event: 'settlement_tx',
      payload: {
        signature: 'abc123signature',
        explorer_url: 'https://explorer.solana.com/tx/abc123signature?cluster=devnet',
        mode: 'live',
      },
    }
    render(<DecisionFeed entries={[tx]} transport="sse" error={null} />)
    const link = screen.getByRole('link', { name: /solana explorer/i })
    expect(link).toHaveAttribute(
      'href',
      'https://explorer.solana.com/tx/abc123signature?cluster=devnet',
    )
  })

  it('does not invent an explorer link when explorer_url is null', () => {
    const tx: DecisionLogEntry = {
      log_id: 'log-000000000004',
      ts: '2026-10-17T12:00:00.000Z',
      schedule_id: 'sch-test',
      actor: 'solana',
      event: 'settlement_tx',
      payload: { signature: 'mocksig-abc', explorer_url: null, mode: 'mock' },
    }
    render(<DecisionFeed entries={[tx]} transport="sse" error={null} />)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByText(/mode=mock/)).toBeInTheDocument()
  })
})
