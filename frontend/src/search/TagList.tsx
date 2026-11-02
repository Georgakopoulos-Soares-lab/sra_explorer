import { useState } from 'react'

// Tags shown before "+N more"; most projects have four or fewer.
const VISIBLE = 5

// A project's tag words as quiet grey chips under its title. Tags that repeat
// the organism (already in its own column) are left out. "+N more" shows the
// rest in place; clicks don't reach the row, so it doesn't expand.
export default function TagList({ tags, organism }: { tags: string[]; organism?: string | null }) {
  const [open, setOpen] = useState(false)
  const shown = tags.filter((t) => t.toLowerCase() !== organism?.toLowerCase())
  if (shown.length === 0) return null
  const hidden = shown.length - VISIBLE
  const visible = open || hidden <= 0 ? shown : shown.slice(0, VISIBLE)

  return (
    <div className="mt-1 flex flex-wrap items-center gap-1 text-xs">
      {visible.map((t) => (
        <span key={t} className="rounded bg-gray-100 px-1.5 py-px text-gray-600">
          {t}
        </span>
      ))}
      {hidden > 0 && (
        <button
          type="button"
          className="cursor-pointer border-0 bg-transparent px-1 text-xs text-blue-600 hover:underline"
          onClick={(e) => {
            e.stopPropagation()
            setOpen(!open)
          }}
        >
          {open ? 'less' : `+${hidden} more`}
        </button>
      )}
    </div>
  )
}
