import { useState } from 'react'
import AdminLayout from '../layouts/AdminLayout'

interface ToolInfo {
  name: string
  description: string
  fieldCount: number
  status: string
}

interface ConnectGuideProps {
  mcpUrl: string
  hostname: string
  tools: ToolInfo[]
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <button
      onClick={handleCopy}
      className="text-xs px-2 py-1 rounded border border-gray-300 hover:bg-gray-50 transition-colors shrink-0"
    >
      {copied ? 'Kopiert!' : 'Kopieren'}
    </button>
  )
}

function ConfigSection({
  title,
  description,
  code,
  link,
  linkText,
  note,
}: {
  title: string
  description: string
  code?: string
  link?: string
  linkText?: string
  note?: string
}) {
  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-2">{title}</h3>
      <p className="text-sm text-gray-500 mb-3">{description}</p>
      {code && (
        <div className="relative">
          <pre className="bg-gray-900 text-green-400 rounded-lg p-4 text-sm font-mono overflow-x-auto whitespace-pre">
            {code}
          </pre>
          <div className="absolute top-2 right-2">
            <CopyButton text={code} />
          </div>
        </div>
      )}
      {note && (
        <p className="text-xs text-gray-400 mt-3 italic">{note}</p>
      )}
      {link && (
        <a
          href={link}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block mt-3 text-sm text-blue-600 hover:text-blue-700 hover:underline"
        >
          {linkText || 'Dokumentation'} →
        </a>
      )}
    </div>
  )
}

export default function ConnectGuide({
  mcpUrl,
  hostname,
  tools,
}: ConnectGuideProps) {
  return (
    <AdminLayout>
      <div className="max-w-3xl">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">
          MCP-Server verbinden
        </h1>
        <p className="text-gray-500 mb-6">
          Verbinden Sie Ihren KI-Assistenten mit dem Agentic.Muenster
          MCP-Server, um Formulare automatisch auszufuellen.
        </p>

        {/* Server Info */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-6 mb-6">
          <h2 className="text-lg font-semibold text-blue-900 mb-3">
            Server-Informationen
          </h2>
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-sm text-blue-700 font-medium w-28">
                MCP URL:
              </span>
              <code className="text-sm font-mono bg-blue-100 px-2 py-1 rounded text-blue-800 flex-1">
                {mcpUrl}
              </code>
              <CopyButton text={mcpUrl} />
            </div>
            <div className="flex items-center gap-3">
              <span className="text-sm text-blue-700 font-medium w-28">
                Transport:
              </span>
              <span className="text-sm text-blue-800">Streamable HTTP</span>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-sm text-blue-700 font-medium w-28">
                Aktive Tools:
              </span>
              <span className="text-sm text-blue-800">
                {tools.length === 0
                  ? 'Keine (erst Formulare freigeben)'
                  : `${tools.length} Formular(e)`}
              </span>
            </div>
          </div>

          {tools.length > 0 && (
            <div className="mt-3 pt-3 border-t border-blue-200">
              {tools.map((tool) => (
                <div
                  key={tool.name}
                  className="text-xs text-blue-700 font-mono"
                >
                  {tool.name}{' '}
                  <span className="text-blue-500">
                    ({tool.fieldCount} Felder)
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Platform configs */}
        <div className="space-y-4">
          <ConfigSection
            title="Claude Desktop / claude.ai"
            description="Fuegen Sie den Server in Ihre Claude-Konfiguration ein."
            code={JSON.stringify(
              {
                mcpServers: {
                  'agentic-muenster': {
                    url: mcpUrl,
                  },
                },
              },
              null,
              2
            )}
            link="https://modelcontextprotocol.io/docs/develop/connect-remote-servers"
            linkText="MCP-Dokumentation"
          />

          <ConfigSection
            title="Claude Code"
            description="Fuehren Sie diesen Befehl im Terminal aus."
            code={`claude mcp add agentic-muenster ${mcpUrl}`}
            link="https://docs.anthropic.com/en/docs/claude-code"
            linkText="Claude Code Dokumentation"
          />

          <ConfigSection
            title="Cursor / VS Code Copilot"
            description="Fuegen Sie den Server in Ihre MCP-Konfiguration ein (settings.json oder .cursor/mcp.json)."
            code={JSON.stringify(
              {
                mcpServers: {
                  'agentic-muenster': {
                    url: mcpUrl,
                  },
                },
              },
              null,
              2
            )}
            link="https://code.visualstudio.com/docs/copilot/chat/mcp-servers"
            linkText="VS Code MCP-Dokumentation"
          />

          <ConfigSection
            title="ChatGPT (Actions)"
            description="ChatGPT unterstuetzt MCP nicht nativ. Sie benoetigen einen OpenAPI-Wrapper oder muessen auf ChatGPTs MCP-Unterstuetzung warten."
            note="ChatGPT verwendet ein eigenes Protokoll (OpenAPI Actions). Eine direkte MCP-Verbindung ist derzeit nicht moeglich."
            link="https://platform.openai.com/docs/actions"
            linkText="OpenAI Actions Dokumentation"
          />

          <ConfigSection
            title="Open WebUI"
            description="Open WebUI unterstuetzt MCP-Tools ueber Pipelines."
            note="Konfigurieren Sie eine Pipeline, die den MCP-Server als Tool-Quelle nutzt."
            link="https://docs.openwebui.com"
            linkText="Open WebUI Dokumentation"
          />

          <ConfigSection
            title="LibreChat"
            description="LibreChat unterstuetzt MCP-Server nativ."
            code={`# In Ihrer LibreChat-Konfiguration:
MCP_SERVERS:
  agentic-muenster:
    url: ${mcpUrl}`}
            link="https://www.librechat.ai"
            linkText="LibreChat Dokumentation"
          />
        </div>
      </div>
    </AdminLayout>
  )
}
