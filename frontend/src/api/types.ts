// GridPulse.ai API types — hand-written from SPEC.md sections 5 and 6.
// JSON keys are snake_case exactly as defined there. Do not rename.

// SPEC 5.1
export type SignalSource =
  | 'synthetic'
  | 'caiso'
  | 'eia'
  | 'watttime'
  | 'electricity_maps'
  | 'wri'

export interface GridSignal {
  ts: string
  price_usd_per_mwh: number
  marginal_gco2_per_kwh: number
  curtailment_mw: number
  water_stress_index: number
  source: SignalSource
}

// SPEC 5.2
export type JobKind = 'compute' | 'ev_charge'

export interface Job {
  job_id: string
  name: string
  kind: JobKind
  checkpointable: boolean
  asset_id: string
  power_kw: number
  duration_h: number
  energy_kwh: number
  release_ts: string
  deadline_ts: string
}

// SPEC 5.3
export type AssetKind = 'data_center' | 'ev_hub'

export interface Asset {
  asset_id: string
  kind: AssetKind
  name: string
  it_capacity_kw: number | null
  charge_capacity_kw: number | null
  wet_extra_kw_per_kw: number | null
  dry_extra_kw_per_kw: number | null
  wet_water_l_per_kwh: number | null
}

// SPEC 5.4
export type ScheduleKind = 'baseline' | 'optimized'

export type ScheduleStatus =
  | 'proposed'
  | 'pending_approval'
  | 'approved'
  | 'applied'
  | 'rejected'
  | 'expired'
  | 'superseded'

export type CoolingMode = 'wet' | 'dry'

export interface SlotJob {
  job_id: string
  fraction: number
}

export interface Slot {
  t: number
  ts: string
  cooling_mode: CoolingMode
  it_load_kw: number
  yw_kw: number
  yd_kw: number
  ev_load_kw: number
  total_load_kw: number
  jobs: SlotJob[]
}

export interface Metrics {
  cost_usd: number
  carbon_kg: number
  water_l: number
  energy_kwh: number
}

export interface SavingsPct {
  cost: number
  carbon: number
  water: number
}

export interface Schedule {
  schedule_id: string
  schedule_kind: ScheduleKind
  status: ScheduleStatus
  alpha: number
  horizon_start: string
  created_at: string
  slots: Slot[]
  metrics: Metrics
  baseline_metrics: Metrics
  savings_pct: SavingsPct
  shifted_job_count: number
  shifted_kwh: number
  savings_label: 'simulated'
  explanation: string | null
}

// SPEC 5.5
export type Actor =
  | 'system'
  | 'optimizer'
  | 'dashboard'
  | 'photon'
  | 'gemini'
  | 'solana'
  | 'grid-agent'
  | 'dc-agent'
  | 'ev-agent'
  | 'bridge'
  | 'simulator'

export type DecisionEvent =
  | 'startup'
  | 'proposed'
  | 'approval_requested'
  | 'sms_sent'
  | 'sms_reply'
  | 'clarification_sent'
  | 'approved'
  | 'rejected'
  | 'applied'
  | 'expired'
  | 'superseded'
  | 'reset'
  | 'error'
  | 'explanation'
  | 'negotiation_msg'
  | 'settlement_tx'
  | 'telemetry_flagged'

export type DecisionPayload = Record<string, unknown>

export interface DecisionLogEntry {
  log_id: string
  ts: string
  schedule_id: string | null
  actor: Actor
  event: DecisionEvent
  payload: DecisionPayload
}

// SPEC 5.6
export interface Telemetry {
  device_id: string
  ts: string
  power_w: number
  temp_c: number
  fan_on: boolean
  simulated: boolean
}

export interface TelemetryMinute {
  bucket: string
  device_id: string
  power_w: number
  temp_c: number
  fan_on: boolean
  simulated: boolean
}

// SPEC 5.7
export interface Constraints {
  max_it_kw?: number
  job_deadlines?: Record<string, string>
}

// SPEC 5.8
export interface OptimizeError {
  code: 'infeasible' | 'solver_error'
  message: string
  job_id: string | null
}

// SPEC 6 — REST shapes
export interface Health {
  status: 'ok'
  mode: 'cached' | 'live'
  hardware_mode: 'real' | 'simulated'
  database: 'sqlite' | 'postgres'
  optimizer_mode: string
  photon_mode: string
  gemini_mode: string
  solana_mode: string
  agents_mode: string
}

export interface OptimizeRequest {
  alpha: number
  constraints?: Constraints | null
}

export interface ExplainResponse {
  schedule_id: string
  text: string
  source: 'gemini' | 'fallback' | 'cache'
}

export interface SignalsResponse {
  horizon_start: string
  items: GridSignal[]
}

export interface JobsResponse {
  items: Job[]
}

export interface AssetsResponse {
  items: Asset[]
}

export interface DecisionsResponse {
  items: DecisionLogEntry[]
}

export interface TelemetryResponse {
  items: TelemetryMinute[]
}

export interface TelemetryCommandResponse {
  command: { fan_on: boolean }
}

export interface ResetResponse {
  status: 'ok'
  applied_schedule_id: string
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details?: Record<string, unknown>
  }
}
