import type { ExplainResponse } from '../api/types'
import { Panel } from './Panel'

const SOURCE_LABEL: Record<ExplainResponse['source'], string> = {
  gemini: 'Gemini',
  fallback: 'template fallback',
  cache: 'cached',
}

export function ExplainCard({
  explanation,
  loading,
  error,
}: {
  explanation: ExplainResponse | null
  loading: boolean
  error: string | null
}) {
  return (
    <Panel
      title="Why this schedule"
      loading={loading}
      error={error}
      right={
        explanation ? (
          <span className="rounded border border-violet-700 bg-violet-950/60 px-2 py-0.5 text-xs text-violet-300">
            {SOURCE_LABEL[explanation.source] ?? explanation.source}
          </span>
        ) : undefined
      }
    >
      {explanation ? (
        <p className="text-sm leading-relaxed text-slate-200">{explanation.text}</p>
      ) : (
        !loading && <p className="text-sm text-slate-500">No explanation yet.</p>
      )}
    </Panel>
  )
}
