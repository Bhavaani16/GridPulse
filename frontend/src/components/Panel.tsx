import type { ReactNode } from 'react'

interface PanelProps {
  title: string
  right?: ReactNode
  loading?: boolean
  error?: string | null
  onRetry?: () => void
  className?: string
  children: ReactNode
}

export function Panel({ title, right, loading, error, onRetry, className, children }: PanelProps) {
  return (
    <section
      className={`rounded-xl border border-slate-800 bg-slate-900/80 p-4 shadow-lg shadow-black/30 ${className ?? ''}`}
    >
      <header className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">{title}</h2>
        <div className="flex items-center gap-2">
          {loading && (
            <span
              className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-600 border-t-sky-400"
              role="status"
              aria-label="loading"
            />
          )}
          {right}
        </div>
      </header>
      {error ? (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-rose-800/60 bg-rose-950/50 px-3 py-2.5">
          <p className="text-sm text-rose-300">{error}</p>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="rounded-md border border-rose-700 px-2.5 py-1 text-xs font-medium text-rose-200 hover:bg-rose-900/60"
            >
              Retry
            </button>
          )}
        </div>
      ) : (
        children
      )}
    </section>
  )
}
