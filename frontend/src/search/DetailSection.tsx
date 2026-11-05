import type { ReactNode } from 'react'

// One part of an expanded result (the project, its publications, similar
// projects): a white box with a header, so the parts read as separate blocks.
export default function DetailSection({ icon, title, extra, children }: {
  icon: ReactNode
  title: ReactNode
  // Shown at the right of the header.
  extra?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="rounded-md border border-gray-200 bg-white">
      <div className="flex items-center gap-2 border-b border-gray-100 px-3 py-2">
        <span className="text-base text-blue-600">{icon}</span>
        <span className="flex-1 font-medium">{title}</span>
        {extra}
      </div>
      <div className="px-3 py-2">{children}</div>
    </section>
  )
}
