import { ExportOutlined } from '@ant-design/icons'
import type { ReactNode } from 'react'

// A link to another site, opened in a new tab, with an icon saying so.
// stopPropagation so clicking it inside a table row doesn't also expand the row.
export default function ExternalLink({ href, children, mono = true }: {
  href: string
  children: ReactNode
  mono?: boolean
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={`inline-flex items-center gap-1 ${mono ? 'font-mono' : ''}`}
      onClick={(e) => e.stopPropagation()}
    >
      {children}
      <ExportOutlined className="text-[0.85em] opacity-70" aria-label="(opens in a new tab)" />
    </a>
  )
}
