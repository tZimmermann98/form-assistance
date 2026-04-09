import { useState } from 'react'

interface FieldChange {
  step: number
  step_title: string
  section: string
  field_label: string
  change_type: string
  old_value: string | null
  new_value: string | null
}

interface StepChange {
  change_type: string
  step: number
  title: string
}

interface DiffData {
  severity: string
  step_changes: StepChange[]
  field_changes: FieldChange[]
  summary_de: string
}

interface DiffViewerProps {
  diff: DiffData
  onAccept?: () => void
}

const SEVERITY_STYLES: Record<string, { bg: string; border: string; text: string; badge: string }> = {
  cosmetic: { bg: 'bg-yellow-50', border: 'border-yellow-200', text: 'text-yellow-800', badge: 'bg-yellow-100 text-yellow-800' },
  structural: { bg: 'bg-orange-50', border: 'border-orange-200', text: 'text-orange-800', badge: 'bg-orange-100 text-orange-800' },
  breaking: { bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-800', badge: 'bg-red-100 text-red-800' },
}

const SEVERITY_LABELS: Record<string, string> = {
  cosmetic: 'Kosmetisch',
  structural: 'Strukturell',
  breaking: 'Kritisch',
}

const CHANGE_LABELS: Record<string, string> = {
  added: 'Neu',
  removed: 'Entfernt',
  type_changed: 'Typ geaendert',
  label_changed: 'Umbenannt',
  required_changed: 'Pflichtfeld geaendert',
  options_changed: 'Optionen geaendert',
}

const CHANGE_COLORS: Record<string, string> = {
  added: 'bg-green-100 text-green-800',
  removed: 'bg-red-100 text-red-800',
  type_changed: 'bg-orange-100 text-orange-800',
  label_changed: 'bg-yellow-100 text-yellow-800',
  required_changed: 'bg-orange-100 text-orange-800',
  options_changed: 'bg-blue-100 text-blue-800',
}

export default function DiffViewer({ diff, onAccept }: DiffViewerProps) {
  const [expanded, setExpanded] = useState(false)
  const style = SEVERITY_STYLES[diff.severity] || SEVERITY_STYLES.cosmetic

  const totalChanges = diff.field_changes.length + diff.step_changes.length

  return (
    <div className={`${style.bg} ${style.border} border rounded-lg mb-6`}>
      {/* Header */}
      <div className="px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className={`text-xs font-semibold px-2 py-0.5 rounded ${style.badge}`}>
            {SEVERITY_LABELS[diff.severity] || diff.severity}
          </span>
          <span className={`text-sm font-medium ${style.text}`}>
            Aenderungen erkannt
          </span>
          <span className="text-xs text-gray-500">
            {diff.summary_de}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setExpanded(!expanded)}
            className={`text-xs px-2 py-1 rounded border ${style.border} ${style.text} hover:bg-white/50 transition-colors`}
          >
            {expanded ? 'Ausblenden' : `${totalChanges} Aenderung(en) anzeigen`}
          </button>
          {onAccept && (
            <button
              onClick={onAccept}
              className="text-xs px-3 py-1 rounded bg-green-600 text-white hover:bg-green-700 transition-colors"
            >
              Akzeptieren & Freigeben
            </button>
          )}
        </div>
      </div>

      {/* Detail */}
      {expanded && (
        <div className="px-4 pb-4 border-t border-gray-200/50 pt-3">
          {/* Step changes */}
          {diff.step_changes.length > 0 && (
            <div className="mb-3">
              <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                Schritt-Aenderungen
              </h4>
              {diff.step_changes.map((sc, i) => (
                <div key={i} className="flex items-center gap-2 text-sm py-1">
                  <span className={`text-xs px-1.5 py-0.5 rounded ${CHANGE_COLORS[sc.change_type] || 'bg-gray-100'}`}>
                    {CHANGE_LABELS[sc.change_type] || sc.change_type}
                  </span>
                  <span className="text-gray-700">
                    Schritt {sc.step}: {sc.title}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Field changes */}
          {diff.field_changes.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                Feld-Aenderungen
              </h4>
              <div className="space-y-1">
                {diff.field_changes.map((fc, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm py-1">
                    <span className={`text-xs px-1.5 py-0.5 rounded shrink-0 ${CHANGE_COLORS[fc.change_type] || 'bg-gray-100'}`}>
                      {CHANGE_LABELS[fc.change_type] || fc.change_type}
                    </span>
                    <div className="min-w-0">
                      <span className="text-gray-700 font-medium">
                        {fc.field_label}
                      </span>
                      <span className="text-gray-400 text-xs ml-2">
                        Schritt {fc.step}: {fc.step_title} / {fc.section}
                      </span>
                      {(fc.old_value || fc.new_value) && (
                        <div className="text-xs text-gray-500 mt-0.5">
                          {fc.old_value && (
                            <span className="line-through text-red-500 mr-2">{fc.old_value}</span>
                          )}
                          {fc.new_value && (
                            <span className="text-green-600">{fc.new_value}</span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
