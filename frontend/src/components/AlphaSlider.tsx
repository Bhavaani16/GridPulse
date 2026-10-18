// Carbon vs water Pareto slider (SPEC 15). Debounces 250 ms before calling
// onOptimize — one POST /api/optimize per gesture, not one per pointer event.

import { useEffect, useRef, useState } from 'react'

const DEBOUNCE_MS = 250

export function AlphaSlider({
  value,
  optimizing,
  onOptimize,
}: {
  value: number
  optimizing: boolean
  onOptimize: (alpha: number) => void
}) {
  const [alpha, setAlpha] = useState(value)
  const [synced, setSynced] = useState(value)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const latest = useRef(onOptimize)

  // External alpha changes (e.g. trigger-surplus re-optimizes at the last
  // alpha) resync the thumb position during render.
  if (value !== synced) {
    setSynced(value)
    setAlpha(value)
  }

  useEffect(() => {
    latest.current = onOptimize
  })
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )

  const handleChange = (next: number) => {
    setAlpha(next)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => latest.current(next), DEBOUNCE_MS)
  }

  return (
    <section
      aria-label="carbon water tradeoff"
      className="rounded-xl border border-slate-800 bg-slate-900/80 p-4 shadow-lg shadow-black/30"
    >
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
          Carbon vs Water
        </h2>
        <p className="text-lg font-bold tabular-nums text-slate-100">
          α = {alpha.toFixed(2)}
          {optimizing && <span className="ml-2 text-xs font-normal text-sky-400">optimizing…</span>}
        </p>
      </div>
      <div className="mt-3 flex items-center gap-4">
        <span className="w-28 text-right text-sm font-medium text-emerald-300">Favor carbon</span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={alpha}
          aria-label="alpha"
          onChange={(e) => handleChange(Number(e.target.value))}
          className="h-2 flex-1 cursor-pointer appearance-none rounded-full bg-gradient-to-r from-emerald-600 via-slate-600 to-sky-600 accent-sky-400"
        />
        <span className="w-28 text-sm font-medium text-sky-300">Favor water</span>
      </div>
      <p className="mt-2 text-xs text-slate-500">
        α weights the water-reduction target: 0 ignores cooling water, 1 uses no wet cooling.
      </p>
    </section>
  )
}
