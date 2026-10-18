import { CheckOutlined, CopyOutlined } from '@ant-design/icons'
import { Button, Tooltip } from 'antd'
import { useState } from 'react'

// A block of code with a language label and a copy button.
export default function CodeBlock({ code, language }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false)

  const copy = () =>
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    })

  return (
    <div className="relative mb-4 overflow-hidden rounded-lg border border-gray-200 bg-gray-50">
      <div className="flex items-center justify-between border-b border-gray-200 px-3 py-1">
        <span className="text-xs uppercase tracking-wide text-gray-500">{language ?? ''}</span>
        <Tooltip title={copied ? 'Copied' : 'Copy'}>
          <Button
            type="text"
            size="small"
            icon={copied ? <CheckOutlined className="text-green-600" /> : <CopyOutlined />}
            onClick={copy}
            aria-label="Copy code"
          />
        </Tooltip>
      </div>
      <pre className="m-0 overflow-x-auto p-3 font-mono text-[13px] leading-relaxed text-gray-800">
        <code>{code}</code>
      </pre>
    </div>
  )
}
