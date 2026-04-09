import FieldCard from './FieldCard'

interface Field {
  label: string
  type: string
  required: boolean
  format?: string
  options?: string[] | string
  help?: string
  conditional_logic?: Record<string, string>
}

interface Section {
  section: string
  group_rule: string | null
  fields: Field[]
}

interface Step {
  step: number
  id: string
  title: string
  description: string
  sections: Section[]
  step_type?: 'auth_gate' | 'info_page' | 'final_page'
  automation_action?: string
  available_actions?: string[]
}

interface FormStepPreviewProps {
  step: Step
}

const STEP_TYPE_STYLES: Record<
  string,
  { bg: string; border: string; text: string; label: string }
> = {
  auth_gate: {
    bg: 'bg-blue-50',
    border: 'border-blue-200',
    text: 'text-blue-800',
    label: 'Anmeldung',
  },
  info_page: {
    bg: 'bg-gray-50',
    border: 'border-gray-200',
    text: 'text-gray-700',
    label: 'Hinweisseite',
  },
  final_page: {
    bg: 'bg-green-50',
    border: 'border-green-200',
    text: 'text-green-800',
    label: 'Abschluss',
  },
}

export default function FormStepPreview({ step }: FormStepPreviewProps) {
  const requiredCount = step.sections.reduce(
    (acc, section) => acc + section.fields.filter((f) => f.required).length,
    0
  )
  const totalCount = step.sections.reduce(
    (acc, section) => acc + section.fields.length,
    0
  )

  // Special step types (auth gate, info page, final page)
  if (step.step_type && STEP_TYPE_STYLES[step.step_type]) {
    const style = STEP_TYPE_STYLES[step.step_type]
    return (
      <div>
        <div className="mb-6">
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-semibold text-gray-900">
              Schritt {step.step}: {step.title}
            </h2>
            <span
              className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${style.bg} ${style.text}`}
            >
              {style.label}
            </span>
          </div>
          <p className="text-sm text-gray-500 mt-1">{step.description}</p>
        </div>

        <div
          className={`${style.bg} ${style.border} border rounded-lg p-5`}
        >
          <div className="flex items-start gap-3">
            <div
              className={`w-8 h-8 rounded-full ${style.bg} ${style.text} flex items-center justify-center shrink-0 text-lg`}
            >
              {step.step_type === 'auth_gate'
                ? '\u{1F512}'
                : step.step_type === 'final_page'
                  ? '\u{1F4C4}'
                  : '\u{2139}\u{FE0F}'}
            </div>
            <div>
              <p className={`text-sm font-medium ${style.text}`}>
                Bei Automatisierung:
              </p>
              <p className={`text-sm ${style.text} mt-1`}>
                {step.automation_action}
              </p>
              {step.available_actions && step.available_actions.length > 0 && (
                <div className="mt-3">
                  <p className={`text-xs font-medium ${style.text} mb-1`}>
                    Verfuegbare Aktionen:
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {step.available_actions.map((action) => (
                      <span
                        key={action}
                        className={`inline-flex items-center px-2 py-0.5 rounded text-xs ${style.bg} ${style.text} border ${style.border}`}
                      >
                        {action}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-xl font-semibold text-gray-900">
          Schritt {step.step}: {step.title}
        </h2>
        <p className="text-sm text-gray-500 mt-1">{step.description}</p>
        <p className="text-xs text-gray-400 mt-1">
          {totalCount} Felder ({requiredCount} Pflichtfelder)
        </p>
      </div>

      <div className="space-y-6">
        {step.sections.map((section) => (
          <div key={section.section}>
            <div className="flex items-center gap-2 mb-3">
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
                {section.section}
              </h3>
              {section.group_rule === 'at_least_one_required' && (
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800">
                  Mindestens eins erforderlich
                </span>
              )}
            </div>

            <div className="space-y-3">
              {section.fields.map((field) => (
                <FieldCard key={field.label} field={field} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
