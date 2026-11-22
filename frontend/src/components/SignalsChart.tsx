// Signals chart (SPEC 15): price, marginal carbon and curtailment per hour.

import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { GridSignal } from '../api/types'
import { hourLabel } from '../utils/format'
import { Panel } from './Panel'

const TOOLTIP_STYLE = {
  backgroundColor: '#0f172a',
  border: '1px solid #334155',
  borderRadius: '0.5rem',
  fontSize: '0.75rem',
}

export function SignalsChart({
  signals,
  loading,
  error,
}: {
  signals: GridSignal[]
  loading: boolean
  error: string | null
}) {
  const data = signals.map((s, t) => ({
    hour: hourLabel(s.ts),
    price_usd_per_mwh: s.price_usd_per_mwh,
    marginal_gco2_per_kwh: s.marginal_gco2_per_kwh,
    curtailment_mw: s.curtailment_mw,
    t,
  }))
  return (
    <Panel title="Grid signals" loading={loading} error={error}>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
            <XAxis dataKey="hour" tick={{ fill: '#64748b', fontSize: 10 }} interval={2} />
            <YAxis
              yAxisId="price"
              tick={{ fill: '#fbbf24', fontSize: 10 }}
              width={36}
              label={{ value: '$/MWh', fill: '#fbbf24', fontSize: 10, angle: -90, position: 'insideLeft' }}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fill: '#34d399', fontSize: 10 }}
              width={36}
              label={{
                value: 'gCO2/kWh · MW',
                fill: '#34d399',
                fontSize: 10,
                angle: 90,
                position: 'insideRight',
              }}
            />
            <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: '#cbd5e1' }} />
            <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
            <Bar
              yAxisId="right"
              dataKey="curtailment_mw"
              isAnimationActive={false}
              name="curtailment (MW)"
              fill="#8b5cf6"
              opacity={0.45}
              radius={[2, 2, 0, 0]}
            />
            <Line
              yAxisId="price"
              type="monotone"
              isAnimationActive={false}
              dataKey="price_usd_per_mwh"
              name="price ($/MWh)"
              stroke="#fbbf24"
              strokeWidth={2}
              dot={false}
            />
            <Line
              yAxisId="right"
              type="monotone"
              isAnimationActive={false}
              dataKey="marginal_gco2_per_kwh"
              name="marginal carbon (gCO2/kWh)"
              stroke="#34d399"
              strokeWidth={2}
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </Panel>
  )
}
