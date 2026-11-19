import {
  ApartmentOutlined,
  ClusterOutlined,
  ExperimentOutlined,
  FilterOutlined,
  InfoCircleOutlined,
  ReadOutlined,
  SearchOutlined,
  TagsOutlined,
} from '@ant-design/icons'
import { Button, Card, Skeleton, Statistic, Tag, Tooltip, Typography } from 'antd'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'
import { api, type Stats } from '../api'
import BrandName from '../components/BrandName'
import { PUBLICATION } from '../config'

const { Title, Paragraph, Text } = Typography

const FEATURES: { icon: ReactNode; title: string; text: string; link?: { to: string; label: string } }[] = [
  {
    icon: <SearchOutlined />,
    title: 'Semantic search',
    text: 'Find datasets by describing them in natural language, beyond exact keyword matches.',
    link: { to: '/search', label: 'Start searching' },
  },
  {
    icon: <TagsOutlined />,
    title: 'Biological tags',
    text: 'Explore organisms, diseases, tissues, cell types and chemicals extracted from project descriptions.',
    link: { to: '/tags', label: 'Tag explorer' },
  },
  {
    icon: <ReadOutlined />,
    title: 'Publication search',
    text: 'Paste a DOI or PubMed ID to find the sequencing datasets behind a paper, or related to it.',
  },
  {
    icon: <FilterOutlined />,
    title: 'Dynamic filters',
    text: 'Narrow results by organism, sample attributes, date and more. Filters show only values that match, with counts.',
  },
  {
    icon: <ExperimentOutlined />,
    title: 'Sequencing details',
    text: 'Filter by assay, instrument, library layout and selection. A project matches when one of its runs fits them all.',
  },
  {
    icon: <ClusterOutlined />,
    title: 'Similar datasets',
    text: 'Open any project to discover related studies by semantic similarity, then go straight to ENA, NCBI and FASTQ files.',
  },
]

const STEPS = [
  {
    title: 'Collect',
    text: 'SRA run metadata, BioProject records and ENA study metadata are downloaded from public NCBI and ENA sources.',
  },
  {
    title: 'Combine',
    text: 'Runs and projects are linked through their SRA study accession in one PostgreSQL database. The sample attributes of over 42 million runs are cleaned and summarised per project.',
  },
  {
    title: 'Enrich',
    text: 'Each project\'s title and description are embedded with a biomedical language model for semantic search, and tag words are extracted from them.',
  },
  {
    title: 'Explore',
    text: 'The search page combines text search with filters across projects, samples and runs, all working together.',
  },
]

const SOURCES = [
  { name: 'NCBI Sequence Read Archive (SRA)', url: 'https://www.ncbi.nlm.nih.gov/sra' },
  { name: 'NCBI BioProject', url: 'https://www.ncbi.nlm.nih.gov/bioproject' },
  { name: 'European Nucleotide Archive (ENA)', url: 'https://www.ebi.ac.uk/ena' },
]

interface StatItem {
  label: string
  value: number | null
  suffix?: ReactNode
  precision?: number
  // A line under the number saying what it means.
  note?: string
  // Shown when hovering the info icon next to the label.
  help?: string
}

function StatsRow() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    api
      .stats(controller.signal)
      .then(setStats)
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true)
      })
    return () => controller.abort()
  }, [])

  if (failed) return null
  const samples = stats ? `${(stats.runs / 1e6).toFixed(1)} million` : ''
  // Share of samples whose submitters recorded the attribute.
  // Number of samples whose submitters recorded the attribute.
  const share = (key: 'tissue' | 'cell_type' | 'cell_line', what: string): StatItem => {
    return {
      label: `Samples with a ${what}`,
      value: stats?.[`${key}_samples`] ?? null,
      note: `of all ${samples} samples have a ${what} recorded`,
      help: `The number of sequencing runs whose sample description, as given by the submitter, names a ${what}. Submitters often leave it out, for example for environmental or bacterial samples, so it is well below the total number of samples. You can filter by ${what} on the search page.`,
    }
  }
  // Studies are SRA studies; "Samples" counts sequencing runs.
  const rows: StatItem[][] = [
    [
      { label: 'Studies', value: stats?.studies ?? null },
      { label: 'Samples', value: stats?.runs ?? null },
      { label: 'Publications', value: stats?.publications ?? null, help: 'Distinct publications linked to the studies, each counted once.' },
    ],
    [
      { label: 'Assay types', value: stats?.assay_types ?? null, help: 'Distinct assay types of the runs, such as RNA-Seq, WGS or ChIP-Seq.' },
      share('tissue', 'tissue'),
      share('cell_type', 'cell type'),
      share('cell_line', 'cell line'),
    ],
  ]
  return (
    <div className="flex flex-col gap-4">
      {rows.map((items, i) => (
        <div key={i} className={`grid grid-cols-2 gap-4 ${items.length === 3 ? 'md:grid-cols-3' : 'md:grid-cols-4'}`}>
          {items.map((item) => (
            <Card key={item.label} size="small">
              {stats ? (
                <>
                  <Statistic
                    title={
                      <span className="inline-flex items-center gap-1">
                        {item.label}
                        {item.help && (
                          <Tooltip title={item.help}>
                            <InfoCircleOutlined className="cursor-help text-gray-400" aria-label={item.help} />
                          </Tooltip>
                        )}
                      </span>
                    }
                    value={item.value ?? '–'}
                    suffix={item.value != null ? item.suffix : undefined}
                    precision={item.value != null ? item.precision : undefined}
                  />
                  {item.note && item.value != null && (
                    <Text type="secondary" className="text-xs">
                      {item.note}
                    </Text>
                  )}
                </>
              ) : (
                <Skeleton active title={false} paragraph={{ rows: 2 }} />
              )}
            </Card>
          ))}
        </div>
      ))}
    </div>
  )
}

export default function HomePage() {
  const navigate = useNavigate()

  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <section className="mb-10 text-center">
        <Title className="!mb-3">
          <BrandName />
        </Title>
        <p className="mx-auto mb-3 max-w-3xl text-2xl font-bold leading-snug text-gray-900 md:text-3xl">
          Beyond keywords. <span className="text-brand-sra">Discover sequencing data.</span>
        </p>
        <Paragraph className="mx-auto max-w-2xl text-lg text-gray-600">
          Explore the NCBI Sequence Read Archive through semantic search, enriched metadata and
          dynamic filters. Describe what you are looking for, search by publication, explore
          biological tags and discover similar datasets.
        </Paragraph>
        <div className="flex flex-wrap justify-center gap-3">
          <Button type="primary" size="large" icon={<SearchOutlined />} onClick={() => navigate('/search')}>
            Search projects
          </Button>
          <Button size="large" href="#cite">
            How to cite
          </Button>
        </div>
      </section>

      <section className="mb-12">
        <StatsRow />
      </section>

      <section className="mb-12">
        <Title level={3}>What you can do</Title>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <Card key={f.title} className="h-full">
              <div className="flex gap-3">
                <span className="text-2xl text-blue-600">{f.icon}</span>
                <div>
                  <div className="mb-1 flex items-center gap-2 font-semibold">
                    {f.title}
                  </div>
                  <Text type="secondary">{f.text}</Text>
                  {f.link && (
                    <div className="mt-1">
                      <Link to={f.link.to}>{f.link.label} →</Link>
                    </div>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      </section>

      <section className="mb-12">
        <Title level={3}>How it works</Title>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s, i) => (
            <Card key={s.title} size="small">
              <div className="mb-1 flex items-center gap-2 font-semibold">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-600 text-xs text-white">
                  {i + 1}
                </span>
                {s.title}
              </div>
              <Text type="secondary">{s.text}</Text>
            </Card>
          ))}
        </div>
      </section>

      <section id="cite" className="mb-12 scroll-mt-6">
        <Title level={3}>How to cite</Title>
        <Card>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Text strong>DOI:</Text>
            {PUBLICATION.doi ? (
              <a href={`https://doi.org/${PUBLICATION.doi}`} target="_blank" rel="noreferrer">
                {PUBLICATION.doi}
              </a>
            ) : (
              <Tag>Pending publication</Tag>
            )}
            {PUBLICATION.venue && <Tag color="blue">{PUBLICATION.venue}</Tag>}
          </div>
          {PUBLICATION.citation ? (
            <Paragraph
              copyable={{
                text: `${PUBLICATION.citation.authors} ${PUBLICATION.citation.title} ${PUBLICATION.citation.source}`,
              }}
              className="!mb-0 rounded bg-gray-50 p-3 font-mono text-sm"
            >
              {PUBLICATION.citation.authors} <strong>{PUBLICATION.citation.title}</strong>{' '}
              {PUBLICATION.citation.source}
            </Paragraph>
          ) : (
            <Text type="secondary">
              The SRAscout paper is not published yet. Its DOI and citation will appear here
              once it is.
            </Text>
          )}
        </Card>
      </section>

      <section>
        <Title level={3}>Data sources</Title>
        <Paragraph type="secondary">
          All data comes from public archives. SRAscout is an independent tool and is not
          affiliated with NCBI or EMBL-EBI.
        </Paragraph>
        <ul className="list-none p-0">
          {SOURCES.map((s) => (
            <li key={s.url} className="mb-2 flex items-center gap-2">
              <ApartmentOutlined className="text-gray-400" />
              <a href={s.url} target="_blank" rel="noreferrer">
                {s.name}
              </a>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-12 border-t border-gray-200 pt-6 text-center">
        <Text type="secondary">
          This work is licensed under{' '}
          <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="license noreferrer">
            CC BY 4.0
          </a>
          .
        </Text>
      </section>
    </div>
  )
}
