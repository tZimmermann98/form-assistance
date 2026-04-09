interface Field {
  label: string
  type: string
  required: boolean
  format?: string
  options?: string[] | string
  help?: string
  conditional_logic?: Record<string, string | { shows_fields?: string[]; hides_fields?: string[]; shows_text?: string }>
}

const TYPE_LABELS: Record<string, { label: string; color: string }> = {
  text: { label: 'Text', color: 'bg-gray-100 text-gray-700' },
  email: { label: 'E-Mail', color: 'bg-blue-100 text-blue-700' },
  select: { label: 'Auswahl', color: 'bg-purple-100 text-purple-700' },
  checkbox: { label: 'Checkbox', color: 'bg-green-100 text-green-700' },
  radio: { label: 'Radio', color: 'bg-orange-100 text-orange-700' },
  date: { label: 'Datum', color: 'bg-pink-100 text-pink-700' },
  textarea: { label: 'Textfeld', color: 'bg-gray-100 text-gray-700' },
}

interface FieldCardProps {
  field: Field
}

export default function FieldCard({ field }: FieldCardProps) {
  const typeInfo = TYPE_LABELS[field.type] ?? {
    label: field.type,
    color: 'bg-gray-100 text-gray-700',
  }

  const options = Array.isArray(field.options) ? field.options : null
  const conditionalEntries = field.conditional_logic
    ? Object.entries(field.conditional_logic)
    : []

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-gray-900">{field.label}</span>
            {field.required && (
              <span className="text-red-500 text-sm font-bold">*</span>
            )}
          </div>

          {field.help && (
            <p className="text-xs text-gray-500 mt-1">{field.help}</p>
          )}

          {field.format && (
            <p className="text-xs text-gray-400 mt-1">
              Format: {field.format}
            </p>
          )}
        </div>

        <span
          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium shrink-0 ${typeInfo.color}`}
        >
          {typeInfo.label}
        </span>
      </div>

      {options && options.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {options.map((opt) => (
            <span
              key={opt}
              className="inline-flex items-center px-2 py-0.5 rounded bg-gray-50 border border-gray-200 text-xs text-gray-600"
            >
              {opt}
            </span>
          ))}
        </div>
      )}

      {typeof field.options === 'string' && (
        <p className="mt-2 text-xs text-gray-400 italic">{field.options}</p>
      )}

      {conditionalEntries.length > 0 && (
        <div className="mt-3 border-t border-gray-100 pt-2">
          <p className="text-xs font-medium text-amber-700 mb-1">
            Bedingte Logik:
          </p>
          {conditionalEntries.map(([condition, result]) => {
            // Handle both old string format and new object format
            let description: string
            if (typeof result === 'string') {
              description = result
            } else {
              const parts: string[] = []
              if (result.shows_fields?.length)
                parts.push(`Zeigt: ${result.shows_fields.join(', ')}`)
              if (result.hides_fields?.length)
                parts.push(`Versteckt: ${result.hides_fields.join(', ')}`)
              if (result.shows_text)
                parts.push(result.shows_text.substring(0, 100))
              description = parts.join('; ') || 'Aendert Formular'
            }
            return (
              <p key={condition} className="text-xs text-amber-600">
                Wenn &laquo;{condition.replace('if_', '')}&raquo; &rarr; {description}
              </p>
            )
          })}
        </div>
      )}
    </div>
  )
}
