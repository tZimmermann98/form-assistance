interface Step {
  step: number
  id: string
  title: string
}

interface StepNavigationProps {
  steps: Step[]
  activeStep: number
  onStepClick: (stepIndex: number) => void
}

export default function StepNavigation({
  steps,
  activeStep,
  onStepClick,
}: StepNavigationProps) {
  return (
    <nav className="space-y-1">
      {steps.map((step, index) => {
        const isActive = index === activeStep
        return (
          <button
            key={step.id}
            onClick={() => onStepClick(index)}
            className={`w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors ${
              isActive
                ? 'bg-blue-50 text-blue-700 font-medium border border-blue-200'
                : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
            }`}
          >
            <div className="flex items-center gap-2.5">
              <span
                className={`flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold shrink-0 ${
                  isActive
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-200 text-gray-600'
                }`}
              >
                {step.step}
              </span>
              <span className="truncate">{step.title}</span>
            </div>
          </button>
        )
      })}
    </nav>
  )
}
