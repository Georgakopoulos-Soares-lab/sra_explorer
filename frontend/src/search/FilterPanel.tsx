import { Badge, Collapse, DatePicker, InputNumber, Segmented, Select, Switch, Typography } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { useEffect, useRef, useState } from 'react'
import { api, type FacetValue, type SearchParams } from '../api'
import { FILTER_SECTIONS, paramKeys, type FilterDef } from './filters'
import type { FilterValues, ParamUpdate } from './useSearchState'

const DATE_FORMAT = 'YYYY-MM-DD'

// With the pointer over an open dropdown, the wheel scrolls only its list,
// never the panel or page behind it. The overscroll-behavior rule in index.css
// does this in Chrome, even for a list too short to scroll; this is a fallback
// for browsers that pass the wheel through such a list, and for the dropdown's
// edges outside the list. It only ever blocks a wheel over a dropdown whose
// list can't scroll that way; if the list isn't found (antd changed its
// markup) it does nothing. Needs a non-passive listener, which React's
// onWheel isn't, so it's added once here.
let wheelLocked = false
function lockDropdownWheel() {
  if (wheelLocked) return
  wheelLocked = true
  document.addEventListener(
    'wheel',
    (e) => {
      const dropdown = (e.target as Element | null)?.closest?.('.ant-select-dropdown')
      if (!dropdown) return
      const list = dropdown.querySelector('.ant-select-dropdown-list-holder')
      if (!list) return
      const canScroll =
        list.contains(e.target as Node) &&
        (e.deltaY < 0 ? list.scrollTop > 0 : list.scrollTop + list.clientHeight < list.scrollHeight - 1)
      if (!canScroll) e.preventDefault()
    },
    { passive: false },
  )
}

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

// The other selected filters, which narrow a filter's options to values found
// among the projects matching them. The filter's own selection is left out, so
// more of its values can still be chosen. Returns the context and a key for it.
function contextFor(def: FilterDef, values: FilterValues): [SearchParams, string] {
  const own = paramKeys(def)
  const context = Object.fromEntries(
    Object.entries(values).filter(([k, v]) => !own.includes(k) && v != null && v !== ''),
  ) as SearchParams
  return [context, JSON.stringify(Object.entries(context).sort())]
}

// Shared across filter panels (sidebar and drawer), by field and context.
// Failed or empty loads are forgotten, so the next open tries again (e.g.
// after data has been loaded).
const facetRequests = new Map<string, Promise<FacetValue[]>>()

function loadFacet(field: string, context: SearchParams, contextKey: string): Promise<FacetValue[]> {
  const key = `${field}|${contextKey}`
  let request = facetRequests.get(key)
  if (!request) {
    request = api.facet(field, context).then((values) => {
      if (values.length === 0) facetRequests.delete(key)
      return values
    })
    request.catch(() => facetRequests.delete(key))
    facetRequests.set(key, request)
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

// No options for an empty query once other filters are chosen means none of
// the matching projects has a value, not that the field is empty.
const emptyStatus = (contextKey: string): LoadStatus => (contextKey === '[]' ? 'empty' : 'loaded')

// Loads its options when the dropdown opens, again whenever the other filters
// have changed since.
function SelectFilter({ def, values, onChange }: Props & { def: FilterDef }) {
  const selected = (values[def.key] as string[] | undefined) ?? []
  const [context, contextKey] = contextFor(def, values)
  const [options, setOptions] = useState<FacetValue[]>([])
  const [status, setStatus] = useState<LoadStatus>('idle')
  const [loadedFor, setLoadedFor] = useState<string>()

  const load = () => {
    if (loadedFor === contextKey && status !== 'error' && status !== 'empty') return
    setLoadedFor(contextKey)
    setStatus('loading')
    loadFacet(def.key, context, contextKey)
      .then((values) => {
        setOptions(values)
        setStatus(values.length ? 'loaded' : emptyStatus(contextKey))
      })
      .catch(() => setStatus('error'))
  }

  return (
    <Select
      mode="multiple"
      // A plain list (not virtual) scrolls natively, so it can stop scrolling
      // from reaching the panel and page (see index.css).
      virtual={false}
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
  const [context, contextKey] = contextFor(def, values)

  // Suggestions for other filters than the current ones are stale; load again
  // on the next focus.
  useEffect(() => {
    setOptions([])
    setStatus('idle')
  }, [contextKey])

  const search = (q: string) => {
    window.clearTimeout(request.current.timer)
    request.current.controller?.abort()
    request.current.timer = window.setTimeout(() => {
      const controller = new AbortController()
      request.current.controller = controller
      setStatus('loading')
      api
        .suggest(def.key, q, controller.signal, context)
        .then((values) => {
          setOptions(values)
          // No matches for an empty query means the field has no values at all.
          setStatus(values.length || q ? 'loaded' : emptyStatus(contextKey))
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
      // A plain list (not virtual) scrolls natively, so it can stop scrolling
      // from reaching the panel and page (see index.css).
      virtual={false}
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
    if (def.kind === 'toggle') {
      return (
        <label className="flex cursor-pointer items-center justify-between gap-2">
          <span className="text-sm">{def.label}</span>
          <Switch
            size="small"
            checked={props.values[def.key] === 'true'}
            onChange={(on) => props.onChange({ [def.key]: on ? 'true' : null })}
          />
        </label>
      )
    }
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
    }[def.kind as Exclude<FilterDef['kind'], 'flag' | 'toggle'>]
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
    useEffect(lockDropdownWheel, [])
    return (
      <>
      {/* Matches contextFor: options are narrowed by the other filters only. */}
      <Typography.Text type="secondary" className="block px-2 pt-3 text-xs">
        Filters update each other: once you choose one, the others list only the values found in
        the matching projects, with their counts.
      </Typography.Text>
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
    </>
  )
}
