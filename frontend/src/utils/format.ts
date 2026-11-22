// Display formatting helpers. Timestamps are UTC ISO-8601 per SPEC 4.

export function relTime(ts: string, nowMs: number = Date.now()): string {
  const diff = nowMs - Date.parse(ts)
  if (Number.isNaN(diff)) return ts
  if (diff < 0) return 'just now'
  const s = Math.floor(diff / 1000)
  if (s < 5) return 'just now'
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

// Slot labels are shown in America/Los_Angeles local time so the duck-curve
// story (solar window 10:00-15:00) reads correctly — signals are anchored to
// local midnight PT (SPEC 4 horizon rebase).
const laHourFmt = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Los_Angeles',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

export function hourLabel(ts: string): string {
  return laHourFmt.format(new Date(ts))
}

export function fmtUsd(n: number): string {
  return `$${n.toFixed(2)}`
}

export function fmtKg(n: number): string {
  return `${n.toFixed(2)} kg`
}

export function fmtLiters(n: number): string {
  return `${n.toFixed(1)} L`
}

/** Share of an hour's cooling that is dry, 0..1. 0 when there is no IT load. */
export function dryShare(ywKw: number, ydKw: number): number {
  const total = ywKw + ydKw
  if (total <= 0) return 0
  return Math.min(1, Math.max(0, ydKw / total))
}

export function fmtPct(n: number): string {
  return `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`
}
