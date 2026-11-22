// FE-1 (SPEC 16): moving the slider queues one POST /api/optimize after
// 250 ms, not one call per pointer event.

import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AlphaSlider } from '../components/AlphaSlider'

describe('AlphaSlider debounce (FE-1)', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('queues exactly one optimize call 250 ms after the last move', () => {
    vi.useFakeTimers()
    const onOptimize = vi.fn()
    render(<AlphaSlider value={0.5} optimizing={false} onOptimize={onOptimize} />)
    const slider = screen.getByLabelText('alpha')

    fireEvent.change(slider, { target: { value: '0.2' } })
    fireEvent.change(slider, { target: { value: '0.6' } })
    fireEvent.change(slider, { target: { value: '0.9' } })

    expect(onOptimize).not.toHaveBeenCalled()
    vi.advanceTimersByTime(249)
    expect(onOptimize).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(onOptimize).toHaveBeenCalledTimes(1)
    expect(onOptimize).toHaveBeenCalledWith(0.9)
  })

  it('fires again for a later gesture', () => {
    vi.useFakeTimers()
    const onOptimize = vi.fn()
    render(<AlphaSlider value={0.5} optimizing={false} onOptimize={onOptimize} />)
    const slider = screen.getByLabelText('alpha')

    fireEvent.change(slider, { target: { value: '0.1' } })
    vi.advanceTimersByTime(250)
    fireEvent.change(slider, { target: { value: '0.4' } })
    vi.advanceTimersByTime(250)

    expect(onOptimize).toHaveBeenCalledTimes(2)
    expect(onOptimize).toHaveBeenLastCalledWith(0.4)
  })

  it('shows the labels and alpha to two decimals', () => {
    render(<AlphaSlider value={0.5} optimizing={false} onOptimize={() => {}} />)
    expect(screen.getByText('Favor carbon')).toBeInTheDocument()
    expect(screen.getByText('Favor water')).toBeInTheDocument()
    expect(screen.getByText(/α = 0\.50/)).toBeInTheDocument()
  })
})
