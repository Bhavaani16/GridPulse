// Schedule action bar (SPEC 15): Request Approval / Approve / Reject with the
// status state machine. Approve is the manual fallback for Photon SMS.

import type { ScheduleStatus } from '../api/types'

const STATUS_STYLE: Record<ScheduleStatus, string> = {
  proposed: 'border-sky-700 bg-sky-950/70 text-sky-300',
  pending_approval: 'border-amber-700 bg-amber-950/70 text-amber-300',
  approved: 'border-emerald-700 bg-emerald-950/70 text-emerald-300',
  applied: 'border-emerald-600 bg-emerald-950/80 text-emerald-200',
  rejected: 'border-rose-700 bg-rose-950/70 text-rose-300',
  expired: 'border-slate-600 bg-slate-900 text-slate-400',
  superseded: 'border-slate-600 bg-slate-900 text-slate-400',
}

const BTN =
  'rounded-lg border px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40'

export function ActionBar({
  status,
  scheduleId,
  busy,
  onRequestApproval,
  onApprove,
  onReject,
}: {
  status: ScheduleStatus
  scheduleId: string
  busy: boolean
  onRequestApproval: () => void
  onApprove: () => void
  onReject: () => void
}) {
  const canRequest = status === 'proposed'
  const canDecide = status === 'proposed' || status === 'pending_approval'
  return (
    <section
      aria-label="schedule actions"
      className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/80 p-4 shadow-lg shadow-black/30"
    >
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">status</span>
        <span
          className={`rounded-full border px-3 py-1 text-sm font-bold ${STATUS_STYLE[status]}`}
          data-testid="schedule-status"
        >
          {status}
        </span>
      </div>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={!canRequest || busy}
          onClick={onRequestApproval}
          className={`${BTN} border-amber-600 bg-amber-950/60 text-amber-200 hover:bg-amber-900/60`}
        >
          Request Approval
        </button>
        <button
          type="button"
          disabled={!canDecide || busy}
          onClick={onApprove}
          className={`${BTN} border-emerald-600 bg-emerald-950/60 text-emerald-200 hover:bg-emerald-900/60`}
        >
          Approve
        </button>
        <button
          type="button"
          disabled={!canDecide || busy}
          onClick={onReject}
          className={`${BTN} border-rose-700 bg-rose-950/60 text-rose-200 hover:bg-rose-900/60`}
        >
          Reject
        </button>
      </div>
      <p className="w-full text-xs text-slate-500">
        {scheduleId} · Approve applies immediately — the manual fallback when the SMS reply is not used.
      </p>
    </section>
  )
}
