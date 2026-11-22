// Live telemetry chart (SPEC 15): power_w and temp_c for the last 5 minutes,
// with fan_on markers.

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
import type { TelemetryMinute } from '../api/types'
import { Panel } from './Panel'

const TOOLTIP_STYLE = {
  backgroundColor: '#0f172a',
  border: '1px solid #334155',
  borderRadius: '0.5rem',
  fontSize: '0.75rem',
}

const minuteLabel = (ts: string) => {
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function TelemetryChart({
  items,
  loading,
  error,
}: {
  items: TelemetryMinute[]
  loading: boolean
  error: string | null
}) {
  const data = items.map((m) => ({
    minute: minuteLabel(m.bucket),
    power_w: m.power_w,
    temp_c: m.temp_c,
    fan_marker: m.fan_on ? 1 : 0,
  }))
  const empty = !loading && !error && data.length === 0
  return (
    <Panel title="Live telemetry — last 5 min" loading={loading} error={error}>
      {empty ? (
        <p className="text-sm text-slate-500">No telemetry in the last 5 minutes.</p>
      ) : (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
              <XAxis dataKey="minute" tick={{ fill: '#64748b', fontSize: 10 }} />
              <YAxis
                yAxisId="power"
                tick={{ fill: '#38bdf8', fontSize: 10 }}
                width={32}
                label={{ value: 'W', fill: '#38bdf8', fontSize: 10, angle: -90, position: 'insideLeft' }}
              />
              <YAxis
                yAxisId="temp"
                orientation="right"
                tick={{ fill: '#fb7185', fontSize: 10 }}
                width={32}
                label={{ value: '°C', fill: '#fb7185', fontSize: 10, angle: 90, position: 'insideRight' }}
              />
              <YAxis yAxisId="fan" hide domain={[0, 10]} />
              <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: '#cbd5e1' }} />
              <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
              <Bar
                yAxisId="fan"
                dataKey="fan_marker"
                isAnimationActive={false}
                name="fan on"
                fill="#a78bfa"
                opacity={0.35}
                legendType="none"
              />
              <Line
                yAxisId="power"
                type="monotone"
                isAnimationActive={false}
                dataKey="power_w"
                name="power (W)"
                stroke="#38bdf8"
                strokeWidth={2}
                dot={{ r: 2.5, fill: '#38bdf8' }}
              />
              <Line
                yAxisId="temp"
                type="monotone"
                isAnimationActive={false}
                dataKey="temp_c"
                name="temperature (°C)"
                stroke="#fb7185"
                strokeWidth={2}
                dot={{ r: 2.5, fill: '#fb7185' }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </Panel>
  )
}
