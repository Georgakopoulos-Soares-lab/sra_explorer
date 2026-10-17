// Client for the ENA Portal API (https://www.ebi.ac.uk/ena/portal/api/).
//
// These requests go straight from the user's browser to ENA, never through
// our backend: ENA rate-limits per client, so each user spends their own
// allowance. ENA allows this with CORS (Access-Control-Allow-Origin: *).

const ENA_API = 'https://www.ebi.ac.uk/ena/portal/api'

const FIELDS = [
  'secondary_study_accession',
  'study_title',
  'submission_accession',
  'experiment_accession',
  'experiment_title',
  'run_accession',
  'run_alias',
  'sample_accession',
  'sample_alias',
  'sample_title',
  'instrument_model',
  'library_name',
  'library_layout',
  'library_strategy',
  'library_source',
  'library_selection',
  'read_count',
  'base_count',
  'fastq_ftp',
  'fastq_bytes',
  'fastq_md5',
  'submitted_ftp',
  'submitted_bytes',
  'submitted_md5',
  'sra_ftp',
  'sra_bytes',
  'sra_md5',
].join(',')

export type FileKind = 'fastq' | 'submitted' | 'sra'

export interface RunFile {
  url: string
  name: string
  bytes: number | null
  md5: string | null
}

export interface EnaRun {
  secondary_study_accession: string
  study_title: string
  submission_accession: string
  experiment_accession: string
  experiment_title: string
  run_accession: string
  run_alias: string
  sample_accession: string
  sample_alias: string
  sample_title: string
  instrument_model: string
  library_name: string
  library_layout: string
  library_strategy: string
  library_source: string
  library_selection: string
  read_count: number | null
  base_count: number | null
  // FASTQ files when ENA has them, otherwise the submitted files, otherwise the SRA file.
  kind: FileKind | null
  files: RunFile[]
}

// Text fields copied from ENA as they are ("" when ENA has no value).
const TEXT_FIELDS = [
  'secondary_study_accession',
  'study_title',
  'submission_accession',
  'experiment_accession',
  'experiment_title',
  'run_accession',
  'run_alias',
  'sample_accession',
  'sample_alias',
  'sample_title',
  'instrument_model',
  'library_name',
  'library_layout',
  'library_strategy',
  'library_source',
  'library_selection',
] as const

type RawRun = Record<string, string>

const splitField = (value: string | undefined) => (value ? value.split(';') : [])
const toNumber = (value: string | undefined) => (value ? Number(value) : null)

// ENA returns host/path without a scheme. Browsers can't open ftp:// links,
// and the same paths are served over HTTPS.
function parseFiles(raw: RawRun, kind: FileKind): RunFile[] {
  const sizes = splitField(raw[`${kind}_bytes`])
  const md5s = splitField(raw[`${kind}_md5`])
  return splitField(raw[`${kind}_ftp`]).map((path, i) => ({
    url: path.startsWith('http') ? path : `https://${path}`,
    name: path.split('/').pop() ?? path,
    bytes: toNumber(sizes[i]),
    md5: md5s[i] || null,
  }))
}

function parseRun(raw: RawRun): EnaRun {
  let kind: FileKind | null = null
  let files: RunFile[] = []
  for (const candidate of ['fastq', 'submitted', 'sra'] as const) {
    files = parseFiles(raw, candidate)
    if (files.length) {
      kind = candidate
      break
    }
  }
  const text = Object.fromEntries(TEXT_FIELDS.map((f) => [f, raw[f] ?? ''])) as Pick<
    EnaRun,
    (typeof TEXT_FIELDS)[number]
  >
  return {
    ...text,
    read_count: toNumber(raw.read_count),
    base_count: toNumber(raw.base_count),
    kind,
    files,
  }
}

async function enaFetch(path: string, params: Record<string, string>, signal?: AbortSignal) {
  const response = await fetch(`${ENA_API}${path}?${new URLSearchParams(params)}`, { signal })
  if (response.status === 429) throw new Error('ENA is rate-limiting requests from your browser. Wait a minute and try again.')
  if (!response.ok) throw new Error(`ENA request failed with status ${response.status}`)
  return response
}

const counts = new Map<string, Promise<number>>()

// Number of runs ENA has for a study (SRP/ERP/DRP accession). Cached for the
// session, so expanding a row and then opening its files page asks only once.
export function countRuns(study: string): Promise<number> {
  let request = counts.get(study)
  if (!request) {
    request = enaFetch('/count', { result: 'read_run', query: `secondary_study_accession=${study}` })
      .then((response) => response.text())
      .then((text) => {
        // The body is "count\n<number>\n".
        const count = Number(text.trim().split('\n').pop())
        if (Number.isNaN(count)) throw new Error('Unexpected response from ENA')
        return count
      })
    request.catch(() => counts.delete(study))
    counts.set(study, request)
  }
  return request
}

// Runs and their files for a study. ENA has no paging (no offset), only a
// limit, so callers cap how many runs they load.
export async function fetchRuns(study: string, limit: number, signal?: AbortSignal): Promise<EnaRun[]> {
  const response = await enaFetch(
    '/filereport',
    { accession: study, result: 'read_run', fields: FIELDS, format: 'json', download: 'true', limit: String(limit) },
    signal,
  )
  const text = await response.text()
  // An unknown accession comes back as an empty body or "[]".
  return text.trim() ? (JSON.parse(text) as RawRun[]).map(parseRun) : []
}

// A link that makes ENA send the whole file report as a TSV download, so
// studies too large to show in the page can still be downloaded in full.
export function fullReportUrl(study: string): string {
  const params = new URLSearchParams({
    accession: study,
    result: 'read_run',
    fields: FIELDS,
    format: 'tsv',
    download: 'true',
    limit: '0',
  })
  return `${ENA_API}/filereport?${params}`
}

export const enaRunUrl = (accession: string) => `https://www.ebi.ac.uk/ena/browser/view/${accession}`

// Formats a number with the largest unit that keeps it at or above 1 (base 1000).
function formatUnits(value: number | null, units: string[]): string {
  if (value === null) return ''
  let unit = 0
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000
    unit++
  }
  return `${value.toFixed(value < 10 && unit > 0 ? 1 : 0)} ${units[unit]}`
}

export const formatBytes = (bytes: number | null) => formatUnits(bytes, ['B', 'KB', 'MB', 'GB', 'TB'])

// Base counts in the units sequencing data is usually described in (e.g. "9.6 Gbp").
export const formatBases = (bases: number | null) => formatUnits(bases, ['bp', 'Kbp', 'Mbp', 'Gbp', 'Tbp'])
