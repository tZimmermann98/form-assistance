import { useState } from 'react'
import { Link, router } from '@inertiajs/react'
import AdminLayout from '../layouts/AdminLayout'

interface ProviderOption {
  value: string
  label: string
  defaultModel: string
}

interface SettingsProps {
  settings: Record<string, string>
  providers: ProviderOption[]
  flash?: { success?: string; error?: string }
}

export default function Settings({
  settings: initial,
  providers,
  flash,
}: SettingsProps) {
  const [form, setForm] = useState({
    llm_provider: initial.llm_provider || 'anthropic',
    llm_base_url: initial.llm_base_url || '',
    llm_api_key: initial.llm_api_key || '',
    llm_model: initial.llm_model || '',
    llm_temperature: initial.llm_temperature || '0.0',
  })
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{
    success: boolean
    response?: string
    error?: string
  } | null>(null)
  const [flashMsg, setFlashMsg] = useState(flash?.success || '')

  const currentProvider = providers.find((p) => p.value === form.llm_provider)
  const showBaseUrl = form.llm_provider === 'custom'

  const handleChange = (key: string, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    setFlashMsg('')
    setTestResult(null)
  }

  const handleProviderChange = (provider: string) => {
    const p = providers.find((pr) => pr.value === provider)
    setForm((prev) => ({
      ...prev,
      llm_provider: provider,
      llm_model: p?.defaultModel || prev.llm_model,
      llm_base_url: provider === 'custom' ? prev.llm_base_url : '',
    }))
    setTestResult(null)
    setFlashMsg('')
  }

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setFlashMsg('')
    router.post('/settings', form, {
      onFinish: () => setSaving(false),
      onSuccess: () => setFlashMsg('Einstellungen gespeichert.'),
    })
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await fetch('/api/v1/settings/test-llm', { method: 'POST' })
      const data = await res.json()
      setTestResult(data)
    } catch {
      setTestResult({ success: false, error: 'Netzwerkfehler' })
    }
    setTesting(false)
  }

  return (
    <AdminLayout>
      <div className="flex items-center gap-2 text-sm text-gray-500 mb-6">
        <Link href="/" className="hover:text-gray-700">
          Dashboard
        </Link>
        <span>/</span>
        <span className="text-gray-900">Einstellungen</span>
      </div>

      <div className="max-w-2xl">
        <h1 className="text-2xl font-bold text-gray-900 mb-6">
          Einstellungen
        </h1>

        {flashMsg && (
          <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-800">
            {flashMsg}
          </div>
        )}

        <form onSubmit={handleSave} className="space-y-6">
          {/* LLM Provider Section */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">
              LLM-Konfiguration
            </h2>
            <p className="text-sm text-gray-500 mb-4">
              Der Explorer nutzt ein LLM um Formularfelder zu interpretieren.
              Buergerdaten werden niemals an das LLM gesendet.
            </p>

            {/* Provider */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Anbieter
              </label>
              <select
                value={form.llm_provider}
                onChange={(e) => handleProviderChange(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              >
                {providers.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Base URL (only for custom) */}
            {showBaseUrl && (
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Base URL
                </label>
                <input
                  type="url"
                  value={form.llm_base_url}
                  onChange={(e) => handleChange('llm_base_url', e.target.value)}
                  placeholder="https://your-llm-server.example.com/v1"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                />
                <p className="text-xs text-gray-400 mt-1">
                  OpenAI-kompatible API (vLLM, Ollama, LiteLLM, etc.)
                </p>
              </div>
            )}

            {/* API Key */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                API-Schluessel
              </label>
              <input
                type="password"
                value={form.llm_api_key}
                onChange={(e) => handleChange('llm_api_key', e.target.value)}
                placeholder={
                  initial.has_api_key
                    ? 'Gespeichert (zum Aendern neuen Schluessel eingeben)'
                    : 'sk-...'
                }
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none font-mono"
              />
              <p className="text-xs text-gray-400 mt-1">
                Wird verschluesselt gespeichert.
              </p>
            </div>

            {/* Model */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Modell
              </label>
              <input
                type="text"
                value={form.llm_model}
                onChange={(e) => handleChange('llm_model', e.target.value)}
                placeholder={currentProvider?.defaultModel || 'model-name'}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none font-mono"
              />
            </div>

            {/* Temperature */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Temperatur:{' '}
                <span className="font-mono">{form.llm_temperature}</span>
              </label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={form.llm_temperature}
                onChange={(e) =>
                  handleChange('llm_temperature', e.target.value)
                }
                className="w-full"
              />
              <div className="flex justify-between text-xs text-gray-400">
                <span>0.0 (deterministisch)</span>
                <span>1.0 (kreativ)</span>
              </div>
            </div>

            {/* Test Connection */}
            <div className="pt-4 border-t border-gray-100">
              <button
                type="button"
                onClick={handleTest}
                disabled={testing}
                className="text-sm px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
              >
                {testing ? 'Teste...' : 'Verbindung testen'}
              </button>

              {testResult && (
                <div
                  className={`mt-3 p-3 rounded-lg text-sm ${
                    testResult.success
                      ? 'bg-green-50 border border-green-200 text-green-800'
                      : 'bg-red-50 border border-red-200 text-red-800'
                  }`}
                >
                  {testResult.success ? (
                    <>
                      Verbindung erfolgreich.
                      {testResult.response && (
                        <span className="ml-1 font-mono text-xs">
                          Antwort: {testResult.response}
                        </span>
                      )}
                    </>
                  ) : (
                    <>Fehler: {testResult.error}</>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Save */}
          <div className="flex gap-3">
            <button
              type="submit"
              disabled={saving}
              className="bg-blue-600 text-white px-6 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors disabled:opacity-50"
            >
              {saving ? 'Speichern...' : 'Speichern'}
            </button>
            <Link
              href="/"
              className="px-6 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50 transition-colors"
            >
              Abbrechen
            </Link>
          </div>
        </form>
      </div>
    </AdminLayout>
  )
}
