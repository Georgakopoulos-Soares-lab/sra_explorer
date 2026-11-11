import { useState } from 'react'

// Tags shown before "+N more"; most projects have four or fewer.
const VISIBLE = 5

// A project's tag words as quiet grey chips under its title. Tags that repeat
// the organism (already in its own column) are left out. Clicking a chip adds
// it to the Tags filter; tags already in the filter are solid blue. "+N more" shows
// the rest in place. Clicks don't reach the row, so it doesn't expand.
export default function TagList({ tags, organism, selected = [], onSelect }: {
  tags: string[]
  organism?: string | null
  selected?: string[]
  onSelect?: (tag: string) => void
}) {
  const [open, setOpen] = useState(false)
  const all = tags.filter((t) => t.toLowerCase() !== organism?.toLowerCase())
  if (all.length === 0) return null
  // Tags in the filter come first and always show, even beyond VISIBLE; the
  // rest keep their relevance order.
  const shown = [...all.filter((t) => selected.includes(t)), ...all.filter((t) => !selected.includes(t))]
  const limit = Math.max(VISIBLE, all.filter((t) => selected.includes(t)).length)
  const hidden = shown.length - limit
  const visible = open || hidden <= 0 ? shown : shown.slice(0, limit)

  return (
    <div className="mt-1 flex flex-wrap items-center gap-1 text-xs">
      {visible.map((t) => {
        const active = selected.includes(t)
        return (
          <button
            key={t}
            type="button"
            title={active ? 'In the Tags filter' : 'Show only projects with this tag'}
            disabled={active || !onSelect}
            className={`rounded border-0 px-1.5 py-px text-xs ${
              active ? 'bg-brand-sra font-medium text-white' : 'cursor-pointer bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
            onClick={(e) => {
              e.stopPropagation()
              onSelect?.(t)
            }}
          >
            {t}
          </button>
        )
      })}
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
