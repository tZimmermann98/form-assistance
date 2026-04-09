import { useState } from 'react'
import { Link, router } from '@inertiajs/react'
import AdminLayout from '../layouts/AdminLayout'
import StatusBadge from '../components/StatusBadge'
import StepNavigation from '../components/StepNavigation'
import FormStepPreview from '../components/FormStepPreview'
import DiffViewer from '../components/DiffViewer'

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
  navigation: { next: string | null; back: string | null }
}

interface Outcome {
  type: string
  description: string
  submission_mode: string
}

interface GraphData {
  steps: Step[]
  outcome: Outcome
}

interface FormData {
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
  approvedBy: string | null
  createdAt: string
}

interface DiffData {
  severity: string
  step_changes: Array<{ change_type: string; step: number; title: string }>
  field_changes: Array<{
    step: number
    step_title: string
    section: string
    field_label: string
    change_type: string
    old_value: string | null
    new_value: string | null
  }>
  summary_de: string
}

interface FormReviewProps {
  form: FormData
  graph: GraphData
  diff: DiffData | null
}

const OUTCOME_LABELS: Record<string, string> = {
  print_and_sign: 'Ausdrucken & Unterschreiben',
  digital_submission: 'Digitale Einreichung',
  download: 'Download',
}

const RECHECK_STATUSES = ['approved', 'outdated', 'degraded']

export default function FormReview({ form, graph, diff }: FormReviewProps) {
  const [activeStep, setActiveStep] = useState(0)

  // Graph may be null if the form is still being explored
  if (!graph || !graph.steps) {
    return (
      <AdminLayout>
        <div className="flex items-center gap-2 text-sm text-gray-500 mb-6">
          <Link href="/" className="hover:text-gray-700">Dashboard</Link>
          <span>/</span>
          <span className="text-gray-900">{form.title}</span>
        </div>
        <div className="flex items-center gap-3 mb-4">
          <h1 className="text-2xl font-bold text-gray-900">{form.title}</h1>
          <StatusBadge status={form.status} />
        </div>
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6 text-center">
          <p className="text-yellow-800 font-medium">Formular-Daten werden noch geladen...</p>
          <p className="text-yellow-600 text-sm mt-1">
            {form.status === 'exploring'
              ? 'Das Formular wird gerade erkundet. Bitte warten Sie, bis die Erkundung abgeschlossen ist.'
              : 'Keine Formular-Graph-Daten verfuegbar.'}
          </p>
          <Link href="/" className="inline-block mt-4 text-sm text-blue-600 hover:underline">
            Zurueck zum Dashboard
          </Link>
        </div>
      </AdminLayout>
    )
  }

  // Handle branching forms
  const isBranching = graph.exploration_type === 'branching'
  const branchPaths = (graph as any).branch_paths as Array<{
    path_id: string
    branch_point: string
    branch_value: string
    steps: Step[]
  }> | undefined
  const commonSteps = (graph as any).common_steps as Step[] | undefined

  const [selectedPath, setSelectedPath] = useState(0)

  // Compute visible steps based on selected path
  const visibleSteps: Step[] = isBranching && commonSteps && branchPaths
    ? [...commonSteps, ...(branchPaths[selectedPath]?.steps || [])]
    : graph.steps

  const currentStep = visibleSteps[activeStep]

  const handleApprove = () => {
    if (confirm('Formular freigeben? Es wird als MCP-Tool veroeffentlicht.')) {
      router.post(`/forms/${form.id}/approve`)
    }
  }

  const handleRecheck = async () => {
    if (!confirm('Das Formular wird erneut exploriert. Fortfahren?')) return

    const res = await fetch(`/api/v1/forms/${form.id}/re-explore`, {
      method: 'POST',
    })
    if (res.ok) {
      const data = await res.json()
      if (data.job_id) {
        router.visit(`/explore/${data.job_id}`)
      }
    }
  }

  const showApprove = form.status !== 'approved' || diff
  const showRecheck = RECHECK_STATUSES.includes(form.status)

  return (
    <AdminLayout>
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 text-sm text-gray-500 mb-2">
          <Link href="/" className="hover:text-gray-700">
            Dashboard
          </Link>
          <span>/</span>
          <span className="text-gray-900">{form.title}</span>
        </div>

        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-gray-900">{form.title}</h1>
              <StatusBadge status={form.status} />
            </div>
            <div className="mt-1 flex items-center gap-4 text-sm text-gray-500">
              <span>{form.organization}</span>
              <span>{form.platform}</span>
              <span>{form.fieldCount} Felder</span>
              <span>v{form.version}</span>
              {form.formId && (
                <span className="font-mono text-xs bg-gray-100 px-2 py-0.5 rounded">
                  {form.formId}
                </span>
              )}
            </div>
            <div className="mt-1 text-xs text-gray-400">{form.sourceUrl}</div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {showRecheck && (
              <button
                onClick={handleRecheck}
                className="border border-gray-300 text-gray-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
              >
                Erneut pruefen
              </button>
            )}
            {showApprove && (
              <button
                onClick={handleApprove}
                className="bg-green-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-green-700 transition-colors"
              >
                Freigeben
              </button>
            )}
          </div>
        </div>

        {form.approvedAt && (
          <div className="mt-2 text-xs text-green-600">
            Freigegeben am{' '}
            {new Date(form.approvedAt).toLocaleDateString('de-DE')} von{' '}
            {form.approvedBy}
          </div>
        )}
      </div>

      {/* Diff banner */}
      {diff && diff.severity !== 'none' && (
        <DiffViewer diff={diff} onAccept={handleApprove} />
      )}

      {/* Path selector for branching forms */}
      {isBranching && branchPaths && branchPaths.length > 0 && (
        <div className="mb-4 p-3 bg-purple-50 border border-purple-200 rounded-lg flex items-center gap-3">
          <span className="text-sm font-medium text-purple-800">
            Verzweigung:
          </span>
          <span className="text-xs text-purple-600">
            {branchPaths[0]?.branch_point}
          </span>
          <div className="flex gap-1">
            {branchPaths.map((bp, i) => (
              <button
                key={bp.path_id}
                onClick={() => { setSelectedPath(i); setActiveStep(0); }}
                className={`px-3 py-1 text-xs rounded-full font-medium transition-colors ${
                  selectedPath === i
                    ? 'bg-purple-600 text-white'
                    : 'bg-purple-100 text-purple-700 hover:bg-purple-200'
                }`}
              >
                {bp.branch_value}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Main content: sidebar + step preview */}
      <div className="flex gap-6">
        {/* Step sidebar */}
        <div className="w-64 shrink-0">
          <div className="sticky top-8">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
              Schritte
            </h3>
            <StepNavigation
              steps={visibleSteps}
              activeStep={activeStep}
              onStepClick={setActiveStep}
            />

            {/* Outcome info */}
            <div className="mt-6 p-3 bg-gray-50 rounded-lg border border-gray-200">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
                Ergebnis
              </h3>
              <p className="text-sm font-medium text-gray-700">
                {OUTCOME_LABELS[graph.outcome.type] ?? graph.outcome.type}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                {graph.outcome.description}
              </p>
            </div>
          </div>
        </div>

        {/* Step content */}
        <div className="flex-1 min-w-0">
          {currentStep && <FormStepPreview step={currentStep} />}

          {/* Step navigation buttons */}
          <div className="mt-8 flex items-center justify-between border-t border-gray-200 pt-4">
            <button
              onClick={() => setActiveStep((s) => Math.max(0, s - 1))}
              disabled={activeStep === 0}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-30 disabled:cursor-not-allowed"
            >
              Vorheriger Schritt
            </button>
            <span className="text-sm text-gray-400">
              Schritt {activeStep + 1} von {visibleSteps.length}
            </span>
            <button
              onClick={() =>
                setActiveStep((s) => Math.min(visibleSteps.length - 1, s + 1))
              }
              disabled={activeStep === visibleSteps.length - 1}
              className="px-4 py-2 text-sm text-blue-600 hover:text-blue-800 font-medium disabled:opacity-30 disabled:cursor-not-allowed"
            >
              Naechster Schritt
            </button>
          </div>
        </div>
      </div>
    </AdminLayout>
  )
}
