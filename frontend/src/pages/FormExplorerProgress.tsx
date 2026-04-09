import { useEffect, useState, useRef } from 'react'
import { Link } from '@inertiajs/react'
import AdminLayout from '../layouts/AdminLayout'
import StatusBadge from '../components/StatusBadge'

interface ProgressEntry {
  step: number
  message: string
  timestamp: string
}

interface Job {
  id: string
  sourceUrl: string
  status: string
  progressLog: ProgressEntry[]
  error: string | null
  formGraphId: string | null
  createdAt: string
}

interface FormExplorerProgressProps {
  job: Job
}

const STATUS_MAP: Record<string, string> = {
  pending: 'exploring',
  running: 'exploring',
  completed: 'review_pending',
  failed: 'exploration_failed',
}

export default function FormExplorerProgress({
  job: initialJob,
}: FormExplorerProgressProps) {
  const [job, setJob] = useState(initialJob)
  const logEndRef = useRef<HTMLDivElement>(null)
  const isTerminal = job.status === 'completed' || job.status === 'failed'

  useEffect(() => {
    if (isTerminal) return

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/v1/explore/${job.id}/status`)
        if (res.ok) {
          const data = await res.json()
          setJob(data)
        }
      } catch {
        // Ignore polling errors
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [job.id, isTerminal])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [job.progressLog.length])

  return (
    <AdminLayout>
      <div className="flex items-center gap-2 text-sm text-gray-500 mb-6">
        <Link href="/" className="hover:text-gray-700">
          Dashboard
        </Link>
        <span>/</span>
        <Link href="/explore" className="hover:text-gray-700">
          Erkunden
        </Link>
        <span>/</span>
        <span className="text-gray-900">Fortschritt</span>
      </div>

      <div className="max-w-3xl">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">
              Formular-Erkundung
            </h1>
            <p className="text-sm text-gray-500 mt-1 truncate max-w-lg">
              {job.sourceUrl}
            </p>
          </div>
          <StatusBadge status={STATUS_MAP[job.status] ?? job.status} />
        </div>

        {/* Progress log */}
        <div className="bg-gray-900 rounded-lg p-4 font-mono text-sm overflow-auto max-h-96">
          {job.progressLog.length === 0 && !isTerminal && (
            <div className="text-gray-500 flex items-center gap-2">
              <span className="animate-pulse">●</span>
              Warte auf Start...
            </div>
          )}
          {job.progressLog.map((entry, i) => (
            <div key={i} className="flex gap-3 py-0.5">
              <span className="text-gray-500 shrink-0 w-6 text-right">
                {entry.step}
              </span>
              <span className="text-green-400">{entry.message}</span>
            </div>
          ))}
          {!isTerminal && job.progressLog.length > 0 && (
            <div className="text-gray-500 flex items-center gap-2 mt-1">
              <span className="animate-pulse">●</span>
            </div>
          )}
          <div ref={logEndRef} />
        </div>

        {/* Error message */}
        {job.status === 'failed' && job.error && (
          <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm font-medium text-red-800">
              Erkundung fehlgeschlagen
            </p>
            <p className="text-sm text-red-600 mt-1">{job.error}</p>
          </div>
        )}

        {/* Completion actions */}
        {job.status === 'completed' && job.formGraphId && (
          <div className="mt-6 p-4 bg-green-50 border border-green-200 rounded-lg flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-green-800">
                Erkundung abgeschlossen
              </p>
              <p className="text-sm text-green-600 mt-0.5">
                Das Formular kann jetzt geprueft und freigegeben werden.
              </p>
            </div>
            <Link
              href={`/forms/${job.formGraphId}`}
              className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-green-700 transition-colors shrink-0"
            >
              Formular pruefen
            </Link>
          </div>
        )}

        {/* Back to dashboard */}
        <div className="mt-6">
          <Link href="/" className="text-sm text-gray-500 hover:text-gray-700">
            Zurueck zum Dashboard
          </Link>
        </div>
      </div>
    </AdminLayout>
  )
}
