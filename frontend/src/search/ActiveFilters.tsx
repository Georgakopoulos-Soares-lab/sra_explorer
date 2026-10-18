import { Button, Tag } from 'antd'
import { ALL_FILTERS, paramKeys } from './filters'
import type { FilterValues, ParamUpdate } from './useSearchState'

interface Chip {
  id: string
  label: string
  remove: ParamUpdate
}

// Each part of a multi-part filter gets its own wording.
const PART_LABELS: Record<string, string> = {
  _from: 'from',
  _to: 'to',
  min_: '≥',
  max_: '≤',
}

function chipsFor(values: FilterValues): Chip[] {
  const chips: Chip[] = []
  for (const def of ALL_FILTERS) {
    for (const key of paramKeys(def)) {
      const value = values[key]
      if (!value) continue
      if (Array.isArray(value)) {
        for (const item of value) {
          chips.push({
            id: `${key}=${item}`,
            label: `${def.label}: ${item}`,
            remove: { [key]: value.filter((v) => v !== item) },
          })
        }
      } else {
        const part = Object.keys(PART_LABELS).find((p) => key.startsWith(p) || key.endsWith(p))
        const text =
          def.kind === 'flag' ? (value === 'true' ? 'yes' : 'no')
          : part ? `${PART_LABELS[part]} ${value}`
          : value
        chips.push({ id: key, label: `${def.label}: ${text}`, remove: { [key]: null } })
      }
    }
  }
  return chips
}

export default function ActiveFilters({ values, accessions = [], onChange, onRemoveAccession, onClear }: {
  values: FilterValues
  // Accessions typed in the search box, shown as chips before the filters.
  accessions?: string[]
  onChange: (update: ParamUpdate) => void
  onRemoveAccession?: (accession: string) => void
  onClear: () => void
}) {
  const chips = chipsFor(values)
  if (chips.length === 0 && accessions.length === 0) return null
  return (
    <div className="mb-3 flex flex-wrap items-center gap-y-1">
      {accessions.map((acc) => (
        <Tag
          key={`accession=${acc}`}
          color="blue"
          closable
          onClose={(e) => {
            e.preventDefault()
            onRemoveAccession?.(acc)
          }}
        >
          Accession: {acc}
        </Tag>
      ))}
      {chips.map((chip) => (
        <Tag
          key={chip.id}
          closable
          onClose={(e) => {
            e.preventDefault()
            onChange(chip.remove)
          }}
        >
          {chip.label}
        </Tag>
      ))}
      <Button type="link" size="small" onClick={onClear}>
        Clear all
      </Button>
    </div>
  )
}
