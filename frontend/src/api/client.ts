// Typed API client for the GridPulse backend (SPEC section 6).
// The only backend base URL is VITE_API_URL. When the health check fails
// the app swaps in the mock client from src/mock/ and shows the banner.

import type {
  ApiErrorBody,
  AssetsResponse,
  DecisionsResponse,
  ExplainResponse,
  Health,
  JobsResponse,
  OptimizeRequest,
  ResetResponse,
  Schedule,
  SignalsResponse,
  TelemetryResponse,
} from './types'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details?: Record<string, unknown>

  constructor(status: number, code: string, message: string, details?: Record<string, unknown>) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

export interface ApiClient {
  health(): Promise<Health>
  getSignals(): Promise<SignalsResponse>
  getJobs(): Promise<JobsResponse>
  getAssets(): Promise<AssetsResponse>
  optimize(request: OptimizeRequest): Promise<Schedule>
  getAppliedSchedule(): Promise<Schedule>
  getSchedule(scheduleId: string): Promise<Schedule>
  requestApproval(scheduleId: string): Promise<Schedule>
  approve(scheduleId: string): Promise<Schedule>
  reject(scheduleId: string): Promise<Schedule>
  explain(scheduleId: string): Promise<ExplainResponse>
  getDecisions(options?: { limit?: number; after?: string }): Promise<DecisionsResponse>
  getTelemetry(minutes?: number): Promise<TelemetryResponse>
  triggerSurplus(): Promise<Schedule>
  resetDemo(): Promise<ResetResponse>
  /** SSE endpoint URL, or null when the client has no stream (mock). */
  streamUrl(): string | null
}

const DEFAULT_TIMEOUT_MS = 10_000

export function createHttpClient(baseUrl: string): ApiClient {
  const base = baseUrl.replace(/\/$/, '')

  async function request<T>(
    path: string,
    init?: RequestInit,
    timeoutMs: number = DEFAULT_TIMEOUT_MS,
  ): Promise<T> {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const response = await fetch(`${base}${path}`, {
        ...init,
        signal: controller.signal,
        headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
      })
      if (!response.ok) {
        let code = 'internal_error'
        let message = `HTTP ${response.status}`
        let details: Record<string, unknown> | undefined
        try {
          const body = (await response.json()) as ApiErrorBody
          code = body.error.code
          message = body.error.message
          details = body.error.details
        } catch {
          // non-JSON error body; keep the generic message
        }
        throw new ApiError(response.status, code, message, details)
      }
      return (await response.json()) as T
    } finally {
      clearTimeout(timer)
    }
  }

  function post<T>(path: string): Promise<T> {
    return request<T>(path, { method: 'POST', body: '{}' })
  }

  return {
    health: () => request<Health>('/api/health', undefined, 5_000),
    getSignals: () => request<SignalsResponse>('/api/signals'),
    getJobs: () => request<JobsResponse>('/api/jobs'),
    getAssets: () => request<AssetsResponse>('/api/assets'),
    optimize: (req) =>
      request<Schedule>('/api/optimize', {
        method: 'POST',
        body: JSON.stringify(req),
      }),
    getAppliedSchedule: () => request<Schedule>('/api/schedules/applied'),
    getSchedule: (id) => request<Schedule>(`/api/schedules/${encodeURIComponent(id)}`),
    requestApproval: (id) =>
      post<Schedule>(`/api/schedules/${encodeURIComponent(id)}/request-approval`),
    approve: (id) => post<Schedule>(`/api/schedules/${encodeURIComponent(id)}/approve`),
    reject: (id) => post<Schedule>(`/api/schedules/${encodeURIComponent(id)}/reject`),
    explain: (id) => request<ExplainResponse>(`/api/explain/${encodeURIComponent(id)}`),
    getDecisions: ({ limit = 50, after } = {}) => {
      const params = new URLSearchParams({ limit: String(limit) })
      if (after) params.set('after', after)
      return request<DecisionsResponse>(`/api/decisions?${params.toString()}`)
    },
    getTelemetry: (minutes = 5) => request<TelemetryResponse>(`/api/telemetry?minutes=${minutes}`),
    triggerSurplus: () => post<Schedule>('/api/demo/trigger-surplus'),
    resetDemo: () => post<ResetResponse>('/api/demo/reset'),
    streamUrl: () => `${base}/api/stream`,
  }
}
