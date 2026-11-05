import {
  ApartmentOutlined,
  ClusterOutlined,
  ExperimentOutlined,
  FilterOutlined,
  InfoCircleOutlined,
  LinkOutlined,
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
    title: 'Describe the data you need',
    text: 'Type what you are looking for in plain language. Semantic and full-text search are combined, so you find projects that describe it in other words as well as those using your exact terms. Or paste BioProject and SRA study accessions.',
  },
  {
    icon: <ExperimentOutlined />,
    title: 'Search by sample',
    text: 'Filter by cell line, cell type, tissue, sex, disease, genotype or strain, treatment and ChIP target, taken from the attributes submitters gave their samples and cleaned up so that different spellings match.',
  },
  {
    icon: <ClusterOutlined />,
    title: 'Search by how data was made',
    text: 'Combine assay type, instrument, library layout, library selection and sequencing center. A project matches when one of its runs fits them all.',
  },
  {
    icon: <FilterOutlined />,
    title: 'Filters that guide you',
    text: 'Also narrow by organism, release date, submitting organisation, size and publications. Each filter only offers values found in projects matching your other choices, with counts, so you see what is available before you search.',
  },
  {
    icon: <TagsOutlined />,
    title: 'Explore by tags',
    text: 'Projects are tagged with the organisms, diseases, tissues, cell types, cell lines and chemicals they describe. Click a tag to find related projects, or add one of the tags common in your results.',
    link: { to: '/tags', label: 'Tag explorer' },
  },
  {
    icon: <LinkOutlined />,
    title: 'Go straight to the source',
    text: 'Every result links to its BioProject page in ENA and its SRA study page at NCBI, shows its publications and GEO series, and lists its FASTQ files with direct download links from ENA.',
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
        <Paragraph className="mx-auto max-w-2xl text-lg text-gray-600">
          Find sequencing datasets in the NCBI Sequence Read Archive. SRAscout brings SRA run
          metadata, sample attributes and BioProject records together, so you can describe the
          data you need, or narrow it down by organism, sample, assay and how it was sequenced.
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
        <div className="grid gap-4 md:grid-cols-2">
          {FEATURES.map((f) => (
            <Card key={f.title}>
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
          </div>
          {PUBLICATION.citation ? (
            <Paragraph copyable className="!mb-0 rounded bg-gray-50 p-3 font-mono text-sm">
              {PUBLICATION.citation}
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
    </div>
  )
}
