import { Badge, Collapse, DatePicker, InputNumber, Segmented, Select, Typography } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { useEffect, useRef, useState } from 'react'
import { api, type FacetValue } from '../api'
import { FILTER_SECTIONS, paramKeys, type FilterDef } from './filters'
import type { FilterValues, ParamUpdate } from './useSearchState'

const DATE_FORMAT = 'YYYY-MM-DD'

interface Props {
  values: FilterValues
  onChange: (update: ParamUpdate) => void
}

// Options carry their count; it's shown in the dropdown, not in the selected tags.
// A count of 0 means unknown (a selected value the latest search didn't return).
const toOptions = (items: FacetValue[]) =>
  items.map(({ value, count, group }) => ({ value, label: value, count, group }))

// Tag suggestions also show the tag's type (disease, tissue, ...) when known.
const renderOption = (option: { label?: React.ReactNode; data: { count: number; group?: string | null } }) => (
  <span className="flex justify-between gap-2">
    <span className="truncate">{option.label}</span>
    <span className="shrink-0 text-gray-400">
      {option.data.group && <span className="mr-2 text-xs">{option.data.group}</span>}
      {option.data.count > 0 && option.data.count.toLocaleString()}
    </span>
  </span>
)

// Shared across filter panels (sidebar and drawer). Failed or empty loads are
// forgotten, so the next open tries again (e.g. after data has been loaded).
const facetRequests = new Map<string, Promise<FacetValue[]>>()

function loadFacet(field: string): Promise<FacetValue[]> {
  let request = facetRequests.get(field)
  if (!request) {
    request = api.facet(field).then((values) => {
      if (values.length === 0) facetRequests.delete(field)
      return values
    })
    request.catch(() => facetRequests.delete(field))
    facetRequests.set(field, request)
  }
  return request
}

// Adds selected values the options don't include, so they still display.
const withSelected = (options: FacetValue[], selected: string[]) => [
  ...options,
  ...selected.filter((v) => !options.some((o) => o.value === v)).map((value) => ({ value, count: 0 })),
]

type LoadStatus = 'idle' | 'loading' | 'loaded' | 'empty' | 'error'

const STATUS_TEXT: Record<LoadStatus, string> = {
  idle: 'Loading…',
  loading: 'Loading…',
  loaded: 'No matches',
  empty: 'No values in the database',
  error: "Couldn't load values. Is the API running?",
}

// Loads its options the first time the dropdown opens.
function SelectFilter({ def, values, onChange }: Props & { def: FilterDef }) {
  const selected = (values[def.key] as string[] | undefined) ?? []
  const [options, setOptions] = useState<FacetValue[]>([])
  const [status, setStatus] = useState<LoadStatus>('idle')

  const load = () => {
    if (status === 'loading' || status === 'loaded') return
    setStatus('loading')
    loadFacet(def.key)
      .then((values) => {
        setOptions(values)
        setStatus(values.length ? 'loaded' : 'empty')
      })
      .catch(() => setStatus('error'))
  }

  return (
    <Select
      mode="multiple"
      allowClear
      className="w-full"
      placeholder="Any"
      loading={status === 'loading'}
      maxTagCount="responsive"
      value={selected}
      options={toOptions(withSelected(options, selected))}
      optionRender={renderOption}
      showSearch
      notFoundContent={STATUS_TEXT[status]}
      onOpenChange={(open) => open && load()}
      onChange={(next: string[]) => onChange({ [def.key]: next })}
    />
  )
}

function SuggestFilter({ def, values, onChange }: Props & { def: FilterDef }) {
  const selected = (values[def.key] as string[] | undefined) ?? []
  const [options, setOptions] = useState<FacetValue[]>([])
  const [status, setStatus] = useState<LoadStatus>('idle')
  const request = useRef<{ timer?: number; controller?: AbortController }>({})
  const scopeKey = def.kind === 'suggest' ? def.scopedBy : undefined
  const scopeValues = scopeKey ? ((values[scopeKey] as string[] | undefined) ?? []) : []
  const scope = scopeKey && scopeValues.length ? { [scopeKey]: scopeValues } : undefined
  const scopeId = scopeValues.join('\n')

  // Suggestions for the old scope are stale; load again on the next focus.
  useEffect(() => {
    setOptions([])
    setStatus('idle')
  }, [scopeId])

  const search = (q: string) => {
    window.clearTimeout(request.current.timer)
    request.current.controller?.abort()
    request.current.timer = window.setTimeout(() => {
      const controller = new AbortController()
      request.current.controller = controller
      setStatus('loading')
      api
        .suggest(def.key, q, controller.signal, scope)
        .then((values) => {
          setOptions(values)
          // No matches for an empty query means the field has no values at all.
          setStatus(values.length || q ? 'loaded' : 'empty')
        })
        .catch(() => {
          if (!controller.signal.aborted) setStatus('error')
        })
    }, 250)
  }

  useEffect(() => {
    const current = request.current
    return () => {
      window.clearTimeout(current.timer)
      current.controller?.abort()
    }
  }, [])

  return (
    <Select
      mode="multiple"
      allowClear
      className="w-full"
      placeholder="Type to search"
      maxTagCount="responsive"
      value={selected}
      options={toOptions(withSelected(options, selected))}
      optionRender={renderOption}
      showSearch={{ filterOption: false, onSearch: search }}
      loading={status === 'loading'}
      notFoundContent={STATUS_TEXT[status]}
      onFocus={() => options.length === 0 && search('')}
      onChange={(next: string[]) => onChange({ [def.key]: next })}
    />
  )
}

function DateRangeFilter({ def, values, onChange }: Props & { def: FilterDef }) {
  const [fromKey, toKey] = paramKeys(def)
  const parse = (v: unknown) => (typeof v === 'string' && v ? dayjs(v, DATE_FORMAT) : null)
  return (
    <DatePicker.RangePicker
      className="w-full"
      allowEmpty={[true, true]}
      value={[parse(values[fromKey]), parse(values[toKey])]}
      onChange={(range: [Dayjs | null, Dayjs | null] | null) =>
        onChange({
          [fromKey]: range?.[0]?.format(DATE_FORMAT) ?? null,
          [toKey]: range?.[1]?.format(DATE_FORMAT) ?? null,
        })
      }
    />
  )
}

// Commits on blur or Enter, so typing a number doesn't search on every keystroke.
// Rendered with key={value}, so it resets when the URL value changes.
function NumberInput({ value, placeholder, onCommit }: {
  value: unknown
  placeholder: string
  onCommit: (value: string | null) => void
}) {
  const external = typeof value === 'string' && value !== '' ? Number(value) : null
  const [draft, setDraft] = useState<number | null>(external)
  const commit = () => {
    if (draft !== external) onCommit(draft === null ? null : String(draft))
  }
  return (
    <InputNumber
      className="!w-full"
      min={0}
      precision={0}
      placeholder={placeholder}
      value={draft}
      onChange={(v) => setDraft(typeof v === 'number' ? v : null)}
      onBlur={commit}
      onPressEnter={commit}
    />
  )
}

function NumberRangeFilter({ def, values, onChange }: Props & { def: FilterDef }) {
  const keys = paramKeys(def)
  return (
    <div className="flex items-center gap-2">
      <NumberInput
        key={String(values[keys[0]])}
        value={values[keys[0]]}
        placeholder="Min"
        onCommit={(v) => onChange({ [keys[0]]: v })}
      />
      {keys[1] && (
        <>
          <span className="text-gray-400">–</span>
          <NumberInput
            key={String(values[keys[1]])}
            value={values[keys[1]]}
            placeholder="Max"
            onCommit={(v) => onChange({ [keys[1]]: v })}
          />
        </>
      )}
    </div>
  )
}

function FlagFilter({ def, values, onChange }: Props & { def: FilterDef }) {
  const value = (values[def.key] as string | undefined) ?? ''
  return (
    <Segmented
      size="small"
      value={value}
      options={[
        { label: 'Any', value: '' },
        { label: 'Yes', value: 'true' },
        { label: 'No', value: 'false' },
      ]}
      onChange={(next) => onChange({ [def.key]: next || null })}
    />
  )
}

function Filter(props: Props & { def: FilterDef }) {
  const { def } = props
  if (def.kind === 'flag') {
    return (
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm">{def.label}</span>
        <FlagFilter {...props} />
      </div>
    )
  }
  const control = {
    select: <SelectFilter {...props} />,
    suggest: <SuggestFilter {...props} />,
    dateRange: <DateRangeFilter {...props} />,
    numberRange: <NumberRangeFilter {...props} />,
    min: <NumberRangeFilter {...props} />,
  }[def.kind]
  return (
    <div>
      <div className="mb-1 text-sm">{def.label}</div>
      {control}
    </div>
  )
}

const isActive = (values: FilterValues, def: FilterDef) =>
  paramKeys(def).some((k) => {
    const v = values[k]
    return Array.isArray(v) ? v.length > 0 : Boolean(v)
  })

export default function FilterPanel(props: Props) {
  return (
    <Collapse
      ghost
      size="small"
      defaultActiveKey={['organism']}
      items={FILTER_SECTIONS.map((section) => {
        const active = section.filters.filter((f) => isActive(props.values, f)).length
        return {
          key: section.key,
          label: (
            <span className="flex items-center gap-2 font-medium">
              {section.title}
              <Badge count={active} size="small" color="blue" />
            </span>
          ),
          children: (
            <div className="flex flex-col gap-3">
              {section.hint && (
                <Typography.Text type="secondary" className="text-xs">
                  {section.hint}
                </Typography.Text>
              )}
              {section.filters.map((def) => (
                <Filter key={def.key} def={def} {...props} />
              ))}
            </div>
          ),
        }
      })}
    />
  )
}
