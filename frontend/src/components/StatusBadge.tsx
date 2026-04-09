const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  exploring: { bg: 'bg-blue-100', text: 'text-blue-800', label: 'Wird erkundet' },
  exploration_failed: { bg: 'bg-red-100', text: 'text-red-800', label: 'Erkundung fehlgeschlagen' },
  review_pending: { bg: 'bg-yellow-100', text: 'text-yellow-800', label: 'Pruefung ausstehend' },
  approved: { bg: 'bg-green-100', text: 'text-green-800', label: 'Freigegeben' },
  outdated: { bg: 'bg-orange-100', text: 'text-orange-800', label: 'Veraltet' },
  degraded: { bg: 'bg-orange-100', text: 'text-orange-800', label: 'Eingeschraenkt' },
  broken: { bg: 'bg-red-100', text: 'text-red-800', label: 'Defekt' },
}

interface StatusBadgeProps {
  status: string
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  const style = STATUS_STYLES[status] ?? {
    bg: 'bg-gray-100',
    text: 'text-gray-800',
    label: status,
  }

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${style.bg} ${style.text}`}
    >
      {style.label}
    </span>
  )
}
