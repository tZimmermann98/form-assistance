import { useState } from 'react'
import { Link, router } from '@inertiajs/react'
import AdminLayout from '../layouts/AdminLayout'

export default function FormExplorer() {
  const [url, setUrl] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!url.trim()) return
    setSubmitting(true)
    router.post('/explore', { url: url.trim() })
  }

  return (
    <AdminLayout>
      <div className="flex items-center gap-2 text-sm text-gray-500 mb-6">
        <Link href="/" className="hover:text-gray-700">
          Dashboard
        </Link>
        <span>/</span>
        <span className="text-gray-900">Neues Formular erkunden</span>
      </div>

      <div className="max-w-2xl">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">
          Formular erkunden
        </h1>
        <p className="text-gray-500 mb-6">
          Geben Sie die URL eines kommunalen Online-Formulars ein. Der Explorer
          navigiert das Formular automatisch und extrahiert alle Felder,
          Schritte und Bedingungen.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="form-url"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Formular-URL
            </label>
            <input
              id="form-url"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://formulare.stadt-muenster.de/..."
              className="w-full px-4 py-3 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              required
              disabled={submitting}
            />
          </div>

          <button
            type="submit"
            disabled={submitting || !url.trim()}
            className="bg-blue-600 text-white px-6 py-3 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? 'Wird gestartet...' : 'Formular erkunden'}
          </button>
        </form>

        <div className="mt-8 p-4 bg-gray-50 rounded-lg border border-gray-200">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">
            Hinweise
          </h3>
          <ul className="text-xs text-gray-500 space-y-1 list-disc list-inside">
            <li>
              Der Explorer arbeitet nur mit leeren Formularen — keine
              Buergerdaten werden verarbeitet.
            </li>
            <li>
              Unterstuetzt werden MACH formsolutions / Apache Wicket Formulare.
            </li>
            <li>Die Erkundung dauert in der Regel 20-30 Sekunden.</li>
          </ul>
        </div>
      </div>
    </AdminLayout>
  )
}
