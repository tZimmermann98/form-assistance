import { Link, router } from '@inertiajs/react'
import AdminLayout from '../layouts/AdminLayout'
import StatusBadge from '../components/StatusBadge'

interface FormSummary {
  id: string
  formId: string | null
  title: string
  sourceUrl: string
  organization: string
  platform: string
  status: string
  version: number
  fieldCount: number
  exploredAt: string | null
  approvedAt: string | null
  createdAt: string
}

interface DashboardProps {
  forms: FormSummary[]
}

export default function Dashboard({ forms }: DashboardProps) {
  return (
    <AdminLayout>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-semibold text-gray-900">Formulare</h2>
        <Link
          href="/explore"
          className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors"
        >
          Neues Formular hinzufuegen
        </Link>
      </div>

      {forms.length === 0 ? (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-12 text-center">
          <p className="text-gray-500 text-lg">
            Noch keine Formulare vorhanden.
          </p>
          <p className="text-gray-400 text-sm mt-2">
            Fuegen Sie ein neues Formular hinzu oder fuehren Sie das Seed-Skript aus.
          </p>
        </div>
      ) : (
        <div className="grid gap-4">
          {forms.map((form) => (
            <Link
              key={form.id}
              href={`/forms/${form.id}`}
              className="block bg-white rounded-lg shadow-sm border border-gray-200 p-6 hover:shadow-md transition-shadow cursor-pointer"
            >
              <div className="flex justify-between items-start">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3">
                    <h3 className="text-lg font-medium text-gray-900 truncate">
                      {form.title}
                    </h3>
                    <StatusBadge status={form.status} />
                  </div>
                  <div className="mt-2 flex items-center gap-4 text-sm text-gray-500">
                    <span>{form.organization}</span>
                    <span>{form.fieldCount} Felder</span>
                    <span>v{form.version}</span>
                    {form.formId && (
                      <span className="font-mono text-xs bg-gray-100 px-2 py-0.5 rounded">
                        {form.formId}
                      </span>
                    )}
                  </div>
                  <div className="mt-1 text-xs text-gray-400 truncate">
                    {form.sourceUrl}
                  </div>
                </div>
                <div className="ml-4 flex-shrink-0 flex items-start gap-3">
                  <div className="text-right text-xs text-gray-400">
                    <div>
                      Erstellt:{' '}
                      {new Date(form.createdAt).toLocaleDateString('de-DE')}
                    </div>
                    {form.exploredAt && (
                      <div>
                        Erkundet:{' '}
                        {new Date(form.exploredAt).toLocaleDateString('de-DE')}
                      </div>
                    )}
                  </div>
                  <button
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      if (confirm(`"${form.title}" wirklich loeschen?`)) {
                        fetch(`/api/v1/forms/${form.id}`, { method: 'DELETE' })
                          .then(() => router.reload())
                      }
                    }}
                    className="text-gray-300 hover:text-red-500 transition-colors p-1"
                    title="Formular loeschen"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </AdminLayout>
  )
}
