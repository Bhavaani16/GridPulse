// Mock fixtures satisfying the exact SPEC section 5 schemas.
// Signal values are the committed duck curve from SPEC 5.1 / data/signals_cached.csv.

import type { Asset, GridSignal, Job } from '../api/types'

// Hour-aligned UTC horizon. Mirrors HORIZON_MODE=today: local midnight in
// America/Los_Angeles on the current date, expressed in UTC.
export function horizonStartUtc(now: Date = new Date()): Date {
  const laParts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Los_Angeles',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now)
  const get = (type: string) => Number(laParts.find((p) => p.type === type)?.value)
  const midnightAsUtc = Date.UTC(get('year'), get('month') - 1, get('day'))
  // UTC offset of America/Los_Angeles at that local midnight (iterate once for DST edges).
  const offsetAt = (instantMs: number) => {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/Los_Angeles',
      hour12: false,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }).formatToParts(new Date(instantMs))
    const num = (type: string) => Number(parts.find((p) => p.type === type)?.value)
    const wall = Date.UTC(
      num('year'),
      num('month') - 1,
      num('day'),
      num('hour') === 24 ? 0 : num('hour'),
      num('minute'),
      num('second'),
    )
    return wall - instantMs
  }
  let start = midnightAsUtc - offsetAt(midnightAsUtc)
  start = midnightAsUtc - offsetAt(start)
  return new Date(start)
}

function hoursAfter(base: Date, h: number): string {
  return new Date(base.getTime() + h * 3_600_000).toISOString().replace(/\.\d{3}Z$/, 'Z')
}

// SPEC 5.1 table, local_hour -> [price, carbon, curtailment, water_stress]
const SIGNAL_TABLE: ReadonlyArray<readonly [number, number, number, number]> = [
  [45.0, 250.0, 5.0, 0.7455],
  [45.0, 250.0, 5.0, 0.738],
  [45.0, 250.0, 5.0, 0.7293],
  [45.0, 250.0, 5.0, 0.72],
  [45.0, 250.0, 5.0, 0.7107],
  [45.0, 250.0, 5.0, 0.702],
  [45.0, 250.0, 5.0, 0.6945],
  [45.0, 250.0, 5.0, 0.6888],
  [45.0, 250.0, 5.0, 0.6852],
  [45.0, 250.0, 5.0, 0.684],
  [20.0, 80.0, 250.0, 0.6852],
  [20.0, 80.0, 250.0, 0.6888],
  [20.0, 80.0, 250.0, 0.6945],
  [20.0, 80.0, 250.0, 0.702],
  [20.0, 80.0, 250.0, 0.7107],
  [20.0, 80.0, 250.0, 0.72],
  [45.0, 250.0, 40.0, 0.7293],
  [45.0, 250.0, 40.0, 0.738],
  [90.0, 420.0, 5.0, 0.7455],
  [90.0, 420.0, 5.0, 0.7512],
  [90.0, 420.0, 5.0, 0.7548],
  [45.0, 250.0, 5.0, 0.756],
  [45.0, 250.0, 5.0, 0.7548],
  [45.0, 250.0, 5.0, 0.7512],
]

export function buildSignals(start: Date = horizonStartUtc()): GridSignal[] {
  return SIGNAL_TABLE.map(([price, carbon, curtailment, wsi], i) => ({
    ts: hoursAfter(start, i),
    price_usd_per_mwh: price,
    marginal_gco2_per_kwh: carbon,
    curtailment_mw: curtailment,
    water_stress_index: wsi,
    source: 'synthetic',
  }))
}

export function buildJobs(start: Date = horizonStartUtc()): Job[] {
  const h = (n: number) => hoursAfter(start, n)
  return [
    { job_id: 'job-cp-01', name: 'Nightly ETL', kind: 'compute', checkpointable: true, asset_id: 'asset-dc-01', power_kw: 5.0, duration_h: 4, energy_kwh: 20.0, release_ts: h(0), deadline_ts: h(24) },
    { job_id: 'job-cp-02', name: 'Feature build', kind: 'compute', checkpointable: true, asset_id: 'asset-dc-01', power_kw: 4.0, duration_h: 3, energy_kwh: 12.0, release_ts: h(8), deadline_ts: h(20) },
    { job_id: 'job-cp-03', name: 'Model eval', kind: 'compute', checkpointable: true, asset_id: 'asset-dc-01', power_kw: 6.0, duration_h: 2, energy_kwh: 12.0, release_ts: h(6), deadline_ts: h(22) },
    { job_id: 'job-cp-04', name: 'Log compaction', kind: 'compute', checkpointable: true, asset_id: 'asset-dc-01', power_kw: 3.0, duration_h: 5, energy_kwh: 15.0, release_ts: h(0), deadline_ts: h(24) },
    { job_id: 'job-ncp-01', name: 'GPU training', kind: 'compute', checkpointable: false, asset_id: 'asset-dc-01', power_kw: 4.0, duration_h: 3, energy_kwh: 12.0, release_ts: h(0), deadline_ts: h(24) },
    { job_id: 'job-ncp-02', name: 'Video transcode', kind: 'compute', checkpointable: false, asset_id: 'asset-dc-01', power_kw: 5.0, duration_h: 2, energy_kwh: 10.0, release_ts: h(9), deadline_ts: h(22) },
    { job_id: 'job-ev-01', name: 'Fleet top-up', kind: 'ev_charge', checkpointable: true, asset_id: 'asset-ev-01', power_kw: 7.0, duration_h: 4, energy_kwh: 28.0, release_ts: h(0), deadline_ts: h(18) },
    { job_id: 'job-ev-02', name: 'Shuttle charge', kind: 'ev_charge', checkpointable: false, asset_id: 'asset-ev-01', power_kw: 11.0, duration_h: 2, energy_kwh: 22.0, release_ts: h(12), deadline_ts: h(24) },
  ]
}

export const MOCK_ASSETS: Asset[] = [
  {
    asset_id: 'asset-dc-01',
    kind: 'data_center',
    name: 'Campus DC',
    it_capacity_kw: 20.0,
    charge_capacity_kw: null,
    wet_extra_kw_per_kw: 0.15,
    dry_extra_kw_per_kw: 0.35,
    wet_water_l_per_kwh: 1.8,
  },
  {
    asset_id: 'asset-ev-01',
    kind: 'ev_hub',
    name: 'Campus EV Hub',
    it_capacity_kw: null,
    charge_capacity_kw: 50.0,
    wet_extra_kw_per_kw: null,
    dry_extra_kw_per_kw: null,
    wet_water_l_per_kwh: null,
  },
]
