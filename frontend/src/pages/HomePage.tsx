import {
  ApartmentOutlined,
  ExperimentOutlined,
  FilterOutlined,
  LinkOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { Button, Card, Skeleton, Statistic, Tag, Typography } from 'antd'
import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { api, type Stats } from '../api'
import BrandName from '../components/BrandName'
import { PUBLICATION } from '../config'

const { Title, Paragraph, Text } = Typography

const FEATURES: { icon: ReactNode; title: string; text: string; soon?: boolean }[] = [
  {
    icon: <FilterOutlined />,
    title: 'Filter projects',
    text: 'Narrow down BioProjects by organism, data type, relevance, release date, size, publications and submitting organisation.',
  },
  {
    icon: <ExperimentOutlined />,
    title: 'Search by how data was made',
    text: 'Find projects with runs from a given assay, sequencing platform, instrument, library layout or sample country.',
  },
  {
    icon: <LinkOutlined />,
    title: 'Go straight to the source',
    text: 'Every result links to its BioProject page in ENA and its SRA study page at NCBI, and lists its FASTQ files with direct download links from ENA.',
  },
  {
    icon: <SearchOutlined />,
    title: 'Semantic search',
    text: 'Describe the data you need in plain language and get the projects that match it best.',
    soon: true,
  },
]

const STEPS = [
  {
    title: 'Collect',
    text: 'SRA run metadata, BioProject records and ENA study metadata are downloaded from public NCBI and ENA sources.',
  },
  {
    title: 'Combine',
    text: 'Runs and projects are cleaned and linked through their SRA study accession in one PostgreSQL database.',
  },
  {
    title: 'Explore',
    text: 'The search page queries that database, so filters across projects and runs work together.',
  },
]

const SOURCES = [
  { name: 'NCBI Sequence Read Archive (SRA)', url: 'https://www.ncbi.nlm.nih.gov/sra' },
  { name: 'NCBI BioProject', url: 'https://www.ncbi.nlm.nih.gov/bioproject' },
  { name: 'European Nucleotide Archive (ENA)', url: 'https://www.ebi.ac.uk/ena' },
]

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
  const items: [string, keyof Stats][] = [
    ['BioProjects', 'bioprojects'],
    ['SRA studies', 'studies'],
    ['Samples', 'runs'],
    ['Organisms', 'organisms'],
  ]
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      {items.map(([label, key]) => (
        <Card key={key} size="small">
          {stats ? (
            <Statistic title={label} value={stats[key]} />
          ) : (
            <Skeleton active title={false} paragraph={{ rows: 2 }} />
          )}
        </Card>
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
          metadata and BioProject records together, so you can search projects by what they
          studied and how their data was sequenced.
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
                </div>
              </div>
            </Card>
          ))}
        </div>
      </section>

      <section className="mb-12">
        <Title level={3}>How it works</Title>
        <div className="grid gap-4 md:grid-cols-3">
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
