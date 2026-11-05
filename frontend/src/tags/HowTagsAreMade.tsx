import { Card, Grid, Steps, Table, Typography } from 'antd'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { api, API_BASE_URL, type Bioproject, type TagOverview } from '../api'
import CodeBlock from '../components/CodeBlock'
import ExternalLink from '../components/ExternalLink'
import ChartCard from '../stats/ChartCard'
import { BarList } from '../stats/charts'
import { formatInt, formatPct } from '../stats/format'

const { Paragraph, Text, Title } = Typography

const NER_MODEL = 'Ihor/gliner-biomed-small-v1.0'
const EMBED_MODEL = 'pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb'
const HF = 'https://huggingface.co'
const DOCS = 'https://github.com/Georgakopoulos-Soares-lab/sra_explorer/blob/main/docs/bioproject-tags.md'
const CODE = 'https://github.com/Georgakopoulos-Soares-lab/sra_explorer/blob/main/Automations/TagWords/extract_tags.py'
// A tagged project shown as a worked example; hidden when it isn't in the database.
const EXAMPLE_PROJECT = 'PRJNA1100990'
const EXAMPLE_CHARS = 700

// The entity types the model is asked for, and whether they are kept as tags.
const TYPES: { type: string; kept: boolean; why?: string }[] = [
  { type: 'organism', kept: true },
  { type: 'disease', kept: true },
  { type: 'tissue', kept: true },
  { type: 'organ', kept: true },
  { type: 'cell type', kept: true },
  { type: 'cell line', kept: true },
  { type: 'chemical or drug', kept: true },
  { type: 'environment or habitat', kept: true },
  { type: 'gene or protein', kept: false, why: 'so gene names are not taken for chemicals or diseases' },
  { type: 'geographic location', kept: false, why: 'so places are not taken for environments' },
  { type: 'sequencing technology', kept: false, why: 'so instrument names are not taken for chemicals' },
]

const API_ROOT = API_BASE_URL.startsWith('http') ? API_BASE_URL : `${window.location.origin}${API_BASE_URL}`

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// The text with every mention of a tag marked.
function Highlighted({ text, tags }: { text: string; tags: string[] }) {
  const parts = useMemo(() => {
    const words = [...tags].filter(Boolean).sort((a, b) => b.length - a.length)
    if (words.length === 0) return [text]
    const re = new RegExp(`(${words.map(escapeRe).join('|')})`, 'gi')
    return text.split(re)
  }, [text, tags])
  const lower = new Set(tags.map((t) => t.toLowerCase()))
  return (
    <>
      {parts.map((part, i) =>
        lower.has(part.toLowerCase()) ? (
          <mark key={i} className="rounded bg-sky-100 px-0.5 text-sky-900">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  )
}

function WorkedExample({ onPick }: { onPick: (tags: string[]) => void }) {
  const [project, setProject] = useState<Bioproject | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    api
      .getBioproject(EXAMPLE_PROJECT, controller.signal)
      .then((rows) => setProject(rows[0] ?? null))
      .catch(() => {}) // the example is an extra; without it the section still reads
    return () => controller.abort()
  }, [])
  if (!project || project.tags.length === 0) return null
  const description = project.description ?? ''
  const excerpt = description.length > EXAMPLE_CHARS ? `${description.slice(0, EXAMPLE_CHARS)}…` : description
  const inText = (t: string) => `${project.title ?? ''} ${description}`.toLowerCase().includes(t.toLowerCase())
  return (
    <Card size="small" title="A worked example" className="min-w-0">
      <Text type="secondary" className="mb-2 block text-xs">
        <ExternalLink href={`https://www.ebi.ac.uk/ena/browser/view/${project.bioproject}`}>{project.bioproject}</ExternalLink>,
        as tagged in the database. Mentions of its tags are marked in the text.
      </Text>
      <div className="mb-2 text-sm font-medium">
        <Highlighted text={project.title ?? project.name ?? ''} tags={project.tags} />
      </div>
      <Paragraph className="!mb-3 text-sm text-gray-700">
        <Highlighted text={excerpt} tags={project.tags} />
      </Paragraph>
      <div className="mb-1 text-xs text-gray-500">Its tags, most relevant first (the organism name always comes first):</div>
      <div className="flex flex-wrap gap-1">
        {project.tags.map((t) => (
          <button
            key={t}
            type="button"
            title={inText(t) ? 'Found in the text. Click to find projects with this tag.' : 'From the organism field. Click to find projects with this tag.'}
            className="cursor-pointer rounded border-0 bg-gray-100 px-1.5 py-px text-xs text-gray-700 hover:bg-gray-200"
            onClick={() => onPick([t])}
          >
            {t}
            {!inText(t) && <span className="ml-1 text-gray-400">(organism field)</span>}
          </button>
        ))}
      </div>
    </Card>
  )
}

// How the tags are made, with the models, thresholds and discarded types; a
// real project as an example; what the tags can't do; the API calls.
export default function HowTagsAreMade({ overview, onPick }: {
  overview: TagOverview
  onPick: (tags: string[]) => void
}) {
  const isDesktop = Grid.useBreakpoint().lg ?? true
  const t = overview.totals
  const count = (tag: string) => overview.top.find((x) => x.value === tag)?.count
  const mouse = count('mouse')
  const mus = count('Mus musculus')

  const steps: { title: string; description: ReactNode }[] = [
    {
      title: 'Entity recognition',
      description: (
        <>
          A biomedical language model (
          <ExternalLink href={`${HF}/${NER_MODEL}`} mono={false}>GLiNER biomed</ExternalLink>) reads the title, name and
          description (the first 300 words, at most 3,000 characters, of that text) and marks every mention of 11 entity types. Eight are kept; three are recognised
          only so that genes, places and sequencers are not mistaken for a kept type.
        </>
      ),
    },
    {
      title: 'Cleanup',
      description: (
        <>
          Ordinary words are lowercased; acronyms, cell lines and species names keep their case (HeLa, C57BL/6J, Mus musculus).
          Plurals become singular, strains are cut to the species, and generic words (cell, sample, patient), accessions and
          instrument names are dropped. Duplicates within a project are merged.
        </>
      ),
    },
    {
      title: 'Relevance filter',
      description: (
        <>
          Each tag is embedded with the same model as the project text (
          <ExternalLink href={`${HF}/${EMBED_MODEL}`} mono={false}>BioBERT</ExternalLink>) and compared with the project's
          embedding by cosine similarity. Tags below 0.10 are passing mentions and are dropped; short acronyms need 0.25.
        </>
      ),
    },
    {
      title: 'Final list',
      description: (
        <>
          The project's organism name comes first. The remaining tags follow in order of relevance, at most 20 per project.
          The same pipeline and thresholds run on every project, and the weekly update tags new projects and works back
          through older ones.
        </>
      ),
    },
  ]

  const apiExamples = [
    `GET ${API_ROOT}/v1/projects?tag=liver&tag=mouse`,
    `GET ${API_ROOT}/v1/projects?tag=mouse&tag=Mus%20musculus&tag_any=true`,
    `GET ${API_ROOT}/v1/filters/tag?q=hepat`,
    `GET ${API_ROOT}/v1/tags/related?tag=liver`,
    `GET ${API_ROOT}/v1/tags/overview`,
  ].join('\n')

  return (
    <section className="mt-10">
      <Title level={3} className="!mb-1">
        How tags are made
      </Title>
      <Paragraph type="secondary">
        Tags are extracted automatically from each project's own description and are not curated. They find projects whose
        text uses other words than yours, but they can be noisy, one thing can appear under several names, and a project that
        never names its tissue has no tissue tag. Read the full method in the{' '}
        <ExternalLink href={DOCS} mono={false}>documentation</ExternalLink> or the{' '}
        <ExternalLink href={CODE} mono={false}>pipeline code</ExternalLink>.
      </Paragraph>
      <Card size="small" className="mb-4">
        <Steps
          type="dot"
          current={steps.length}
          orientation={isDesktop ? 'horizontal' : 'vertical'}
          items={steps.map((s) => ({
            title: s.title,
            content: <span className="text-xs text-gray-600">{s.description}</span>,
          }))}
        />
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <WorkedExample onPick={onPick} />
        <Card size="small" title="Entity types" className="min-w-0">
          <Text type="secondary" className="mb-2 block text-xs">
            What the model is asked to find, and which types become tags.
          </Text>
          <Table
            size="small"
            pagination={false}
            rowKey="type"
            dataSource={TYPES}
            columns={[
              { title: 'Type', dataIndex: 'type', width: 180 },
              {
                title: 'Kept as a tag',
                dataIndex: 'kept',
                render: (kept: boolean, row) => (kept ? 'Yes' : <span>No, {row.why}</span>),
              },
            ]}
          />
        </Card>

        {overview.has_labels ? (
          <ChartCard
            title="Tag occurrences by type"
            csvName="tag_types"
            table={{
              columns: [
                { key: 'value', title: 'Type' },
                { key: 'count', title: 'Tag occurrences', numeric: true },
                { key: 'distinct', title: 'Distinct tags', numeric: true },
              ],
              rows: overview.types.map((x) => ({ value: x.value, count: x.count, distinct: x.distinct })),
            }}
            caption={
              <>
                Each tag's type, over the {formatInt(t.labelled)} projects whose tags have types ({formatPct((100 * t.labelled) / Math.max(t.tagged, 1))} of
                the tagged projects). A tag counts once per project.
              </>
            }
          >
            <BarList
              format={formatInt}
              items={overview.types.map((x) => ({
                label: x.value,
                value: x.count,
                detail: (
                  <div className="tabular-nums">
                    {formatInt(x.count)} occurrences, {formatInt(x.distinct)} distinct tags
                  </div>
                ),
              }))}
            />
          </ChartCard>
        ) : (
          <Card size="small" title="Tag types" className="min-w-0">
            <Text type="secondary" className="text-sm">
              The type of each tag (organism, disease, tissue, …) is kept for projects tagged since types were added to the
              pipeline, and shown next to the tag in the Tags filter. {formatInt(t.labelled)} of the {formatInt(t.tagged)}{' '}
              tagged projects have types so far. Projects tagged earlier keep their tags without types until the tags are
              rebuilt from scratch.
            </Text>
          </Card>
        )}

        <Card size="small" title="What tags can't do yet" className="min-w-0">
          <ul className="m-0 list-disc space-y-1.5 pl-5 text-sm">
            <li>
              <Text strong>Partial coverage.</Text> {formatInt(t.tagged)} of {formatInt(t.projects)} BioProjects (
              {formatPct((100 * t.tagged) / Math.max(t.projects, 1))}) have tags. A tag search leaves out the rest; the search
              page's text search still finds every project.
            </li>
            <li>
              <Text strong>Synonyms are not merged.</Text>{' '}
              {mouse && mus ? (
                <>
                  <i>mouse</i> ({formatInt(mouse)} projects) and <i>Mus musculus</i> ({formatInt(mus)}) are separate tags, as are{' '}
                  <i>E. coli</i> and <i>Escherichia coli</i>.
                </>
              ) : (
                <>
                  <i>mouse</i> and <i>Mus musculus</i> are separate tags, as are <i>E. coli</i> and <i>Escherichia coli</i>.
                </>
              )}{' '}
              Choose both with <i>Any of the tags</i>. Mapping tags to NCBI Taxonomy, MONDO, UBERON, the Cell Ontology,
              Cellosaurus and ChEBI is planned.
            </li>
            <li>
              <Text strong>Exact, case-sensitive matching.</Text> Spellings that differ only in case are separate tags; the
              type-ahead finds them all.
            </li>
            <li>
              <Text strong>Only the start of long texts</Text> (the first 300 words of title, name and description) is
              read, and some multi-word tags are noisy phrases rather than entities.
            </li>
          </ul>
        </Card>
      </div>

      <Card size="small" title="Tags in the API" className="mt-4">
        <Text type="secondary" className="mb-2 block text-xs">
          The same tag queries from a script, rate-limited to one request per 5 seconds. See the{' '}
          <Link to="/docs/api">API documentation</Link>.
        </Text>
        <CodeBlock code={apiExamples} language="http" />
      </Card>
    </section>
  )
}
