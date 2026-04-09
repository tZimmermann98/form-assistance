import type { ReactNode } from 'react'
import { Link, usePage } from '@inertiajs/react'
import NotificationBell from '../components/NotificationBell'

interface AdminLayoutProps {
  children: ReactNode
}

export default function AdminLayout({ children }: AdminLayoutProps) {
  const { url } = usePage()

  const navLinks = [
    { href: '/', label: 'Formulare' },
    { href: '/explore', label: 'Erkunden' },
    { href: '/test-chat', label: 'Test-Chat' },
    { href: '/connect', label: 'Verbinden' },
    { href: '/settings', label: 'Einstellungen' },
  ]

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16 items-center">
            <div className="flex items-center gap-6">
              <Link href="/" className="flex items-center gap-2">
                <h1 className="text-xl font-bold text-gray-900">
                  Agentic.Munster
                </h1>
                <span className="text-xs bg-blue-100 text-blue-800 px-2 py-0.5 rounded-full font-medium">
                  v0.1
                </span>
              </Link>
              <div className="flex items-center gap-1">
                {navLinks.map((link) => {
                  const isActive =
                    link.href === '/'
                      ? url === '/'
                      : url.startsWith(link.href)
                  return (
                    <Link
                      key={link.href}
                      href={link.href}
                      className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                        isActive
                          ? 'bg-gray-100 text-gray-900'
                          : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
                      }`}
                    >
                      {link.label}
                    </Link>
                  )
                })}
              </div>
            </div>
            <NotificationBell />
          </div>
        </div>
      </nav>
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>
    </div>
  )
}
