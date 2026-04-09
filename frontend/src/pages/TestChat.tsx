import { useState, useRef, useEffect } from 'react'
import { Link } from '@inertiajs/react'
import AdminLayout from '../layouts/AdminLayout'

interface ToolInfo {
  name: string
  description: string
  fieldCount: number
}

interface TestChatProps {
  hasApiKey: boolean
  provider: string
  model: string
  availableTools: ToolInfo[]
}

interface Message {
  role: 'user' | 'assistant' | 'tool_call' | 'tool_result'
  content: string
  toolName?: string
  toolArgs?: Record<string, unknown>
  toolId?: string
  screenshot?: string  // base64 PNG
  pdfUrl?: string      // download URL
}

export default function TestChat({
  hasApiKey,
  provider,
  model,
  availableTools,
}: TestChatProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [attachments, setAttachments] = useState<Array<{ name: string; base64: string }>>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files) return
    for (const file of Array.from(files)) {
      const reader = new FileReader()
      reader.onload = () => {
        const base64 = (reader.result as string).split(',')[1]
        setAttachments((prev) => [...prev, { name: file.name, base64 }])
      }
      reader.readAsDataURL(file)
    }
    e.target.value = ''
  }

  const removeAttachment = (index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index))
  }

  const sendMessage = async () => {
    if (!input.trim() || loading) return
    let content = input.trim()
    if (attachments.length > 0) {
      const names = attachments.map((a) => a.name).join(', ')
      content += `\n\n[Angehängte Dateien: ${names}]`
    }
    const userMsg: Message = { role: 'user', content }
    const newMessages = [...messages, userMsg]
    const currentAttachments = [...attachments]
    setMessages(newMessages)
    setInput('')
    setAttachments([])
    setLoading(true)

    try {
      await runAgentLoop(newMessages, currentAttachments)
    } finally {
      setLoading(false)
    }
  }

  const runAgentLoop = async (
    currentMessages: Message[],
    currentAttachments: Array<{ name: string; base64: string }> = [],
  ) => {
    // Convert our messages to API format
    const apiMessages = currentMessages
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .map((m) => ({ role: m.role, content: m.content }))

    // Also include tool results as assistant context
    for (const msg of currentMessages) {
      if (msg.role === 'tool_call' && msg.toolId) {
        apiMessages.push({
          role: 'assistant',
          content: `[Tool-Aufruf: ${msg.toolName}(${JSON.stringify(msg.toolArgs)})]`,
        })
      }
      if (msg.role === 'tool_result') {
        apiMessages.push({
          role: 'user' as const,
          content: `[Tool-Ergebnis: ${msg.content}]`,
        })
      }
    }

    const res = await fetch('/api/v1/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        messages: apiMessages,
        attachments: currentAttachments.length > 0 ? currentAttachments : undefined,
      }),
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Netzwerkfehler' }))
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `Fehler: ${err.detail || 'Unbekannter Fehler'}`,
        },
      ])
      return
    }

    const data = await res.json()
    const blocks = data.blocks || []

    let updatedMessages = [...currentMessages]

    for (const block of blocks) {
      if (block.type === 'text') {
        updatedMessages.push({
          role: 'assistant',
          content: block.content,
        })
      } else if (block.type === 'tool_call') {
        // Show the tool call
        updatedMessages.push({
          role: 'tool_call',
          content: `${block.name}`,
          toolName: block.name,
          toolArgs: block.arguments,
          toolId: block.id,
        })
        setMessages([...updatedMessages])

        // Execute the tool
        const toolRes = await fetch('/api/v1/chat/execute-tool', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            tool_name: block.name,
            arguments: block.arguments,
            attachments: currentAttachments.length > 0 ? currentAttachments : undefined,
          }),
        })

        const toolData = await toolRes.json()
        updatedMessages.push({
          role: 'tool_result',
          content: toolData.result || 'Kein Ergebnis',
          screenshot: toolData.screenshot || undefined,
          pdfUrl: toolData.pdf_url || undefined,
        })
        setMessages([...updatedMessages])

        // Continue the agent loop with the tool result
        await runAgentLoop(updatedMessages)
        return
      }
    }

    setMessages(updatedMessages)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <AdminLayout>
      <div className="flex gap-6 h-[calc(100vh-8rem)]">
        {/* Sidebar: Available tools */}
        <div className="w-64 shrink-0">
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">
              Verfuegbare Formulare
            </h3>
            {availableTools.length === 0 ? (
              <p className="text-xs text-gray-400">
                Keine freigegebenen Formulare.{' '}
                <Link href="/" className="text-blue-500 hover:underline">
                  Dashboard
                </Link>
              </p>
            ) : (
              <div className="space-y-2">
                {availableTools.map((tool) => (
                  <div
                    key={tool.name}
                    className="p-2 bg-green-50 border border-green-200 rounded text-xs"
                  >
                    <div className="font-medium text-green-800 font-mono">
                      {tool.name}
                    </div>
                    <div className="text-green-600 mt-0.5">
                      {tool.fieldCount} Felder
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="mt-4 pt-3 border-t border-gray-100 text-xs text-gray-400">
              <div>Anbieter: {provider}</div>
              {model && <div>Modell: {model}</div>}
              {!hasApiKey && (
                <div className="mt-2 text-orange-500">
                  Kein API-Schluessel konfiguriert.{' '}
                  <Link href="/settings" className="underline">
                    Einstellungen
                  </Link>
                </div>
              )}
            </div>
          </div>

          <button
            onClick={() => setMessages([])}
            className="mt-3 w-full text-xs text-gray-500 border border-gray-200 rounded-lg px-3 py-2 hover:bg-gray-50 transition-colors"
          >
            Chat leeren
          </button>
        </div>

        {/* Chat area */}
        <div className="flex-1 flex flex-col bg-white rounded-lg shadow-sm border border-gray-200">
          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.length === 0 && (
              <div className="flex items-center justify-center h-full text-gray-400 text-sm">
                Stellen Sie eine Frage oder bitten Sie um Hilfe beim Ausfuellen
                eines Formulars.
              </div>
            )}

            {messages.map((msg, i) => (
              <ChatMessage key={i} message={msg} />
            ))}

            {loading && (
              <div className="flex gap-2 items-center text-gray-400 text-sm">
                <span className="animate-pulse">●</span> Denkt nach...
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="border-t border-gray-200 p-4">
            {/* Attachment chips */}
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-1 mb-2">
                {attachments.map((att, i) => (
                  <span
                    key={i}
                    className="inline-flex items-center gap-1 bg-blue-50 border border-blue-200 text-blue-700 text-xs px-2 py-1 rounded-full"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                    </svg>
                    {att.name}
                    <button
                      onClick={() => removeAttachment(i)}
                      className="text-blue-400 hover:text-blue-700"
                    >
                      x
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="flex gap-2">
              <input
                ref={fileInputRef}
                type="file"
                onChange={handleFileSelect}
                multiple
                className="hidden"
                accept=".pdf,.jpg,.jpeg,.png,.doc,.docx"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={loading || !hasApiKey}
                className="px-3 py-2 border border-gray-300 rounded-lg text-gray-500 hover:bg-gray-50 transition-colors disabled:opacity-50 shrink-0"
                title="Datei anhaengen"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                </svg>
              </button>
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Nachricht eingeben..."
                disabled={loading || !hasApiKey}
                className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none disabled:bg-gray-50"
              />
              <button
                onClick={sendMessage}
                disabled={loading || !input.trim() || !hasApiKey}
                className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
              >
                Senden
              </button>
            </div>
          </div>
        </div>
      </div>
    </AdminLayout>
  )
}

function ChatMessage({ message }: { message: Message }) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[70%] bg-blue-600 text-white px-4 py-2 rounded-lg rounded-br-sm text-sm whitespace-pre-wrap">
          {message.content}
        </div>
      </div>
    )
  }

  if (message.role === 'assistant') {
    return (
      <div className="flex justify-start">
        <div className="max-w-[70%] bg-gray-100 text-gray-900 px-4 py-2 rounded-lg rounded-bl-sm text-sm whitespace-pre-wrap">
          {message.content}
        </div>
      </div>
    )
  }

  if (message.role === 'tool_call') {
    return (
      <div className="flex justify-start">
        <ToolCallCard
          toolName={message.toolName || ''}
          toolArgs={message.toolArgs || {}}
        />
      </div>
    )
  }

  if (message.role === 'tool_result') {
    return (
      <div className="flex justify-start">
        <div className="max-w-[80%] bg-gray-50 border border-gray-200 px-4 py-2 rounded-lg text-xs text-gray-600">
          <span className="text-gray-400 text-[10px] uppercase tracking-wider block mb-1">
            Tool-Ergebnis
          </span>
          <div className="font-mono whitespace-pre-wrap">
            {message.content.length > 500
              ? message.content.slice(0, 500) + '...'
              : message.content}
          </div>

          {/* Screenshot of the filled form */}
          {message.screenshot && (
            <div className="mt-3">
              <img
                src={`data:image/png;base64,${message.screenshot}`}
                alt="Ausgefuelltes Formular"
                className="max-w-full rounded border border-gray-300"
              />
            </div>
          )}

          {/* PDF download button */}
          {message.pdfUrl && (
            <div className="mt-3">
              <a
                href={message.pdfUrl}
                download="formular.pdf"
                className="inline-flex items-center gap-2 bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-green-700 transition-colors"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                PDF herunterladen
              </a>
            </div>
          )}
        </div>
      </div>
    )
  }

  return null
}

function ToolCallCard({
  toolName,
  toolArgs,
}: {
  toolName: string
  toolArgs: Record<string, unknown>
}) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="max-w-[80%] bg-amber-50 border border-amber-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-2 flex items-center gap-2 text-sm text-amber-800 hover:bg-amber-100 transition-colors"
      >
        <span className="text-amber-500">⚡</span>
        <span className="font-medium font-mono">{toolName}</span>
        <span className="text-amber-500 text-xs ml-auto">
          {expanded ? '▼' : '▶'}
        </span>
      </button>
      {expanded && (
        <div className="px-4 py-2 border-t border-amber-200 bg-amber-50">
          <pre className="text-xs text-amber-700 font-mono whitespace-pre-wrap">
            {JSON.stringify(toolArgs, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
