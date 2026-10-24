import { ClockCircleOutlined, ExportOutlined } from '@ant-design/icons'
import { Alert, Anchor, Grid, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useEffect, useState, type ReactNode } from 'react'
import { api, API_BASE_URL, type PublicApiDocs, type PublicApiFilter } from '../api'
import CodeBlock from '../components/CodeBlock'

const { Title, Paragraph, Text } = Typography

// The public API lives under /v1 of the backend. In development the backend is
// reached through the frontend's /api proxy, so the base URL follows that.
const API_ROOT = API_BASE_URL.startsWith('http') ? API_BASE_URL : `${window.location.origin}${API_BASE_URL}`
const BASE = `${API_ROOT}/v1`

const SECTIONS = [
  { key: 'overview', title: 'Overview' },
  { key: 'rate-limit', title: 'Rate limit' },
  { key: 'endpoints', title: 'Endpoints' },
  { key: 'info', title: 'GET /v1', indent: true },
  { key: 'search', title: 'GET /v1/projects', indent: true },
  { key: 'lookup', title: 'GET /v1/projects/{accession}', indent: true },
  { key: 'filters', title: 'GET /v1/filters', indent: true },
  { key: 'filter-values', title: 'GET /v1/filters/{name}', indent: true },
  { key: 'semantic', title: 'GET /v1/projects/semantic', indent: true },
  { key: 'parameters', title: 'Search parameters' },
  { key: 'errors', title: 'Errors' },
  { key: 'full-example', title: 'Full Python example' },
  { key: 'versioning', title: 'Versioning' },
]

function Section({ id, title, level = 2, children }: { id: string; title: ReactNode; level?: 2 | 3; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-6 pb-6">
      <Title level={level} className={level === 2 ? '!mt-6' : '!mt-4'}>
        {title}
      </Title>
      {children}
    </section>
  )
}

function Route({ path, soon }: { path: string; soon?: boolean }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Tag color="green" className="!m-0 font-mono">GET</Tag>
      <span className="font-mono">{path}</span>
      {soon && <Tag color="gold" className="!m-0">Not available yet</Tag>}
    </span>
  )
}

// A request URL with a link to open it. Opening it counts against the rate limit.
function Request({ path }: { path: string }) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2">
      <Tag color="green" className="!m-0 font-mono">GET</Tag>
      <Text code copyable={{ text: `${BASE}${path}` }} className="break-all">
        {`${BASE}${path}`}
      </Text>
      <a href={`${BASE}${path}`} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 text-sm">
        Try it <ExportOutlined />
      </a>
    </div>
  )
}

interface Param {
  name: string
  type: string
  description: ReactNode
}

function Params({ rows }: { rows: Param[] }) {
  return (
    <Table<Param>
      className="mb-4"
      size="small"
      pagination={false}
      rowKey="name"
      dataSource={rows}
      columns={[
        { title: 'Parameter', dataIndex: 'name', width: 180, render: (v: string) => <Text code>{v}</Text> },
        { title: 'Type', dataIndex: 'type', width: 110 },
        { title: 'Description', dataIndex: 'description' },
      ]}
    />
  )
}

const KIND_LABELS: Record<string, string> = {
  list: 'Text, repeatable',
  date: 'Date',
  integer: 'Integer',
  boolean: 'true / false',
  string: 'Text',
}

const filterColumns: TableColumnsType<PublicApiFilter> = [
  { title: 'Parameter', dataIndex: 'name', width: 200, render: (v: string) => <Text code>{v}</Text> },
  { title: 'Type', dataIndex: 'kind', width: 140, render: (v: string) => KIND_LABELS[v] ?? v },
  { title: 'Description', dataIndex: 'description' },
  {
    title: 'Allowed values',
    dataIndex: 'values',
    width: 260,
    render: (v: string | null) => (v ? <Text code>{v}</Text> : null),
  },
]

export default function ApiDocsPage() {
  const isDesktop = Grid.useBreakpoint().lg ?? true
  const [docs, setDocs] = useState<PublicApiDocs | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    api
      .publicApiDocs(controller.signal)
      .then(setDocs)
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true)
      })
    return () => controller.abort()
  }, [])

  // Shown before the docs load, and if they can't be loaded.
  const seconds = docs?.rate_limit_seconds ?? 5
  const wait = `${seconds} second${seconds === 1 ? '' : 's'}`

  return (
    <div className="mx-auto flex max-w-[1400px] gap-8 px-4 py-8">
      {isDesktop && (
        <aside className="w-60 shrink-0">
          <div className="sticky top-6">
            <Anchor
              offsetTop={24}
              items={SECTIONS.map((s) => ({
                key: s.key,
                href: `#${s.key}`,
                title: <span className={s.indent ? 'pl-3 font-mono text-xs' : ''}>{s.title}</span>,
              }))}
            />
          </div>
        </aside>
      )}

      <main className="min-w-0 flex-1 rounded-lg bg-white px-6 py-4 lg:px-10">
        <Title className="!mb-2">Public API</Title>
        <Paragraph className="text-base text-gray-600">
          Search SRAscout's BioProject and SRA study records from your own scripts and tools. The API is
          read-only, needs no account or key, and returns JSON.
        </Paragraph>

        <Section id="overview" title="Overview">
          <Paragraph>All endpoints use HTTP GET and live under this base URL:</Paragraph>
          <CodeBlock code={BASE} />
          <ul className="mb-4 list-disc pl-6">
            <li>Responses are JSON. Errors are JSON too, with a <Text code>detail</Text> message.</li>
            <li>No authentication: requests are limited per IP address instead (see below).</li>
            <li>
              Results are the same as on the <a href="/search">search page</a>: each result is one BioProject
              and SRA study pair, with all its fields (title, description, organism, dates, publications, and
              so on).
            </li>
          </ul>
          <Paragraph>
            The Python examples use the <Text code>requests</Text> library (<Text code>pip install requests</Text>).
          </Paragraph>
        </Section>

        <Section id="rate-limit" title="Rate limit">
          <Alert
            className="mb-4"
            type="warning"
            showIcon
            icon={<ClockCircleOutlined />}
            title={`1 request every ${wait} per IP address`}
            description={`This applies to every /v1 endpoint together. Opening a "Try it" link on this page counts too.`}
          />
          <Paragraph>
            A request sent sooner is rejected with status <Text code>429 Too Many Requests</Text>. The{' '}
            <Text code>Retry-After</Text> header says how many seconds to wait, and the body explains:
          </Paragraph>
          <CodeBlock
            language="json"
            code={`{"detail": "Rate limit exceeded: 1 request per ${seconds} seconds. Try again in 4 s."}`}
          />
          <Paragraph>
            Rejected requests don't restart the wait, so retrying after <Text code>Retry-After</Text> always
            works. To fetch many results, ask for 100 per request (<Text code>limit=100</Text>) and pause between
            requests:
          </Paragraph>
          <CodeBlock
            language="python"
            code={`import time
import requests

def get(url, params=None):
    """GET from the API, waiting and retrying when rate-limited."""
    while True:
        r = requests.get(url, params=params)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", ${seconds})))
            continue
        r.raise_for_status()
        return r.json()`}
          />
        </Section>

        <Section id="endpoints" title="Endpoints">
          <Table
            className="mb-2"
            size="small"
            pagination={false}
            rowKey="path"
            dataSource={[
              { path: '/v1', purpose: 'API version, rate limit and list of endpoints' },
              { path: '/v1/projects', purpose: 'Search projects with filters' },
              { path: '/v1/projects/{accession}', purpose: 'Look up a project by BioProject or SRA study accession' },
              { path: '/v1/filters', purpose: 'Every search parameter, with a description' },
              { path: '/v1/filters/{name}', purpose: 'The values of a list filter, with counts' },
              { path: '/v1/projects/semantic', purpose: 'Search by describing the data (not available yet)' },
            ]}
            columns={[
              { title: 'Endpoint', dataIndex: 'path', width: 320, render: (v: string) => <Route path={v} /> },
              { title: 'Purpose', dataIndex: 'purpose' },
            ]}
          />

          <Section id="info" level={3} title={<Route path="/v1" />}>
            <Paragraph>Returns the API version, the rate limit and the list of endpoints. Takes no parameters.</Paragraph>
            <Request path="" />
            <CodeBlock
              language="json"
              code={`{
  "version": "v1",
  "rate_limit": "1 request per ${seconds} seconds per IP",
  "endpoints": {
    "search": "/v1/projects",
    "lookup": "/v1/projects/{accession}",
    "filters": "/v1/filters",
    "filter_values": "/v1/filters/{name}",
    "semantic_search": "/v1/projects/semantic (not available yet)"
  }
}`}
            />
          </Section>

          <Section id="search" level={3} title={<Route path="/v1/projects" />}>
            <Paragraph>
              Searches projects. Every parameter is optional; with none, it returns all projects, newest first.
              How parameters combine:
            </Paragraph>
            <ul className="mb-4 list-disc pl-6">
              <li>
                <Text strong>Several values for one parameter match any of them.</Text> Repeat the parameter:{' '}
                <Text code>?platform=ILLUMINA&amp;platform=PACBIO_SMRT</Text>. In Python, pass a list.
              </li>
              <li>
                <Text strong>Different parameters must all match.</Text>
              </li>
              <li>
                Run parameters (<Text code>assay_type</Text>, <Text code>platform</Text>,{' '}
                <Text code>librarylayout</Text>, <Text code>sample_country</Text>, …) match projects that have
                runs with those values.
              </li>
            </ul>
            <Paragraph>The most used parameters (all of them are listed under <a href="#parameters">Search parameters</a>):</Paragraph>
            <Params
              rows={[
                { name: 'accession', type: 'Text', description: 'BioProject (PRJNA, PRJEB, PRJDB) or SRA study (SRP, ERP, DRP) accession. Repeatable, any case.' },
                { name: 'organism', type: 'Text', description: <>Organism name, exactly as listed by <Text code>/v1/filters/organism</Text>.</> },
                { name: 'supergroup', type: 'Text', description: 'e.g. Bacteria, Eukaryotes, Viruses' },
                { name: 'assay_type', type: 'Text', description: 'Run assay type, e.g. RNA-Seq, WGS, AMPLICON' },
                { name: 'platform', type: 'Text', description: 'e.g. ILLUMINA, OXFORD_NANOPORE, PACBIO_SMRT' },
                { name: 'release_from / release_to', type: 'Date', description: 'Project release date range, YYYY-MM-DD' },
                { name: 'min_experiments', type: 'Integer', description: 'Projects with at least this many experiments' },
                { name: 'has_publications', type: 'true / false', description: 'Only projects with (or without) publications' },
                { name: 'sort', type: 'Text', description: <>Order of results. Default <Text code>release_desc</Text> (newest first).</> },
                { name: 'limit', type: 'Integer', description: 'Results per request, 1–100. Default 25.' },
                { name: 'offset', type: 'Integer', description: 'Number of results to skip, for paging. Default 0.' },
              ]}
            />
            <Request path="/projects?supergroup=Bacteria&platform=OXFORD_NANOPORE&limit=2" />
            <Paragraph>
              The response gives the total number of matches and one page of results. To get the next page, add{' '}
              <Text code>limit</Text> to <Text code>offset</Text>.
            </Paragraph>
            <CodeBlock
              language="json"
              code={`{
  "total": 3216,
  "limit": 2,
  "offset": 0,
  "results": [
    {
      "bioproject": "PRJDB13601",
      "sra_study": "DRP018874",
      "title": "Whole genome sequence of Lactobacillus acetotolerans G3",
      "organism_name": "Lactobacillus acetotolerans",
      "n_experiments": 1,
      "project_release_date": "2026-05-13",
      "publication_count": 0,
      "...": "all other fields"
    }
  ]
}`}
            />
            <CodeBlock
              language="python"
              code={`import requests

params = {
    "supergroup": "Bacteria",
    "platform": ["OXFORD_NANOPORE", "PACBIO_SMRT"],  # a list = any of these
    "has_publications": "true",
    "limit": 10,
}
data = requests.get("${BASE}/projects", params=params).json()

print(data["total"], "projects")
for project in data["results"]:
    print(project["bioproject"], project["sra_study"], project["title"])`}
            />
          </Section>

          <Section id="lookup" level={3} title={<Route path="/v1/projects/{accession}" />}>
            <Paragraph>
              Finds a project by its BioProject or SRA study accession (any case). A BioProject with several SRA
              studies returns one result per study, so the response is always a list. An unknown accession returns{' '}
              <Text code>404</Text>; something that isn't a valid accession returns <Text code>422</Text>.
            </Paragraph>
            <Request path="/projects/PRJDB16527" />
            <CodeBlock
              language="json"
              code={`{
  "results": [
    {
      "bioproject": "PRJDB16527",
      "sra_study": "DRP018889",
      "title": "Effect of the role of SMG1 and DNA-PK inhibitors in response to diethylmalate treatment in PC3 cells",
      "...": "all other fields"
    }
  ]
}`}
            />
            <CodeBlock
              language="python"
              code={`import requests

r = requests.get("${BASE}/projects/SRP079428")
if r.status_code == 404:
    print("Not found")
else:
    for project in r.json()["results"]:
        print(project["bioproject"], project["title"])`}
            />
            <Paragraph type="secondary">
              To look up several accessions in one request, use the search endpoint:{' '}
              <Text code>/v1/projects?accession=PRJNA169753&amp;accession=SRP048511</Text>.
            </Paragraph>
          </Section>

          <Section id="filters" level={3} title={<Route path="/v1/filters" />}>
            <Paragraph>
              Lists every parameter of <Text code>/v1/projects</Text>, with its type and a description. For list
              parameters, <Text code>values</Text> says where to find the allowed values. The same list is shown
              under <a href="#parameters">Search parameters</a> below.
            </Paragraph>
            <Request path="/filters" />
            <CodeBlock
              language="json"
              code={`[
  {"name": "accession", "kind": "list", "description": "BioProject (PRJNA, PRJEB, PRJDB) or SRA study (SRP, ERP, DRP) accession", "values": null},
  {"name": "organism", "kind": "list", "description": "Project organism name", "values": "/v1/filters/organism?q=..."},
  {"name": "release_from", "kind": "date", "description": "YYYY-MM-DD", "values": null},
  "..."
]`}
            />
          </Section>

          <Section id="filter-values" level={3} title={<Route path="/v1/filters/{name}" />}>
            <Paragraph>
              Returns the values a list parameter can take, most common first, with how many projects (for project
              parameters) or studies (for run parameters) have each. Use it to find the exact spelling to pass to{' '}
              <Text code>/v1/projects</Text>.
            </Paragraph>
            <Params
              rows={[
                { name: 'q', type: 'Text', description: 'Only values containing this text (any case). Useful for long lists like organism.' },
                { name: 'limit', type: 'Integer', description: 'Maximum number of values, 1–1000. Default 100.' },
              ]}
            />
            <Request path="/filters/organism?q=homo&limit=3" />
            <CodeBlock
              language="json"
              code={`[
  {"value": "Homo sapiens", "count": 67894},
  {"value": "Stenotrophomonas maltophilia", "count": 69},
  {"value": "Xanthomonas oryzae pv. oryzae", "count": 52}
]`}
            />
            <CodeBlock
              language="python"
              code={`import requests

platforms = requests.get("${BASE}/filters/platform").json()
for item in platforms[:5]:
    print(f'{item["value"]}: {item["count"]:,} studies')`}
            />
          </Section>

          <Section id="semantic" level={3} title={<Route path="/v1/projects/semantic" soon />}>
            <Paragraph>
              Will search projects by a plain-language description of the data, for example{' '}
              <Text code>single-cell RNA-seq of human liver</Text>. It isn't available yet: it currently returns{' '}
              <Text code>501 Not Implemented</Text>. The URL is reserved, so code written against it will work once
              it's released.
            </Paragraph>
            <Params rows={[{ name: 'q', type: 'Text', description: 'Required. The description of the data you are looking for.' }]} />
            <CodeBlock language="json" code={`{"detail": "Semantic search is not available yet."}`} />
          </Section>
        </Section>

        <Section id="parameters" title="Search parameters">
          <Paragraph>
            Every parameter of <Text code>/v1/projects</Text>. Parameters marked “repeatable” accept several values.
          </Paragraph>
          {failed ? (
            <Alert
              type="info"
              showIcon
              title={
                <>
                  The parameter list couldn't be loaded here. Get it from <Text code>{`${BASE}/filters`}</Text>.
                </>
              }
            />
          ) : (
            <Table<PublicApiFilter>
              size="small"
              rowKey="name"
              loading={!docs}
              dataSource={docs?.filters ?? []}
              columns={filterColumns}
              pagination={false}
              scroll={{ x: 800 }}
            />
          )}
        </Section>

        <Section id="errors" title="Errors">
          <Table
            size="small"
            pagination={false}
            rowKey="status"
            dataSource={[
              { status: '404', meaning: 'No project with that accession.' },
              { status: '422', meaning: 'A parameter is invalid. detail says which one and why.' },
              { status: '429', meaning: `Rate limit exceeded. Wait the number of seconds in the Retry-After header.` },
              { status: '501', meaning: 'Semantic search is not available yet.' },
            ]}
            columns={[
              { title: 'Status', dataIndex: 'status', width: 100, render: (v: string) => <Text code>{v}</Text> },
              { title: 'Meaning', dataIndex: 'meaning' },
            ]}
          />
        </Section>

        <Section id="full-example" title="Full Python example">
          <Paragraph>
            Downloads every RNA-Seq project with samples from Greece, 100 per request, respecting the rate limit,
            and saves them to a CSV file.
          </Paragraph>
          <CodeBlock
            language="python"
            code={`import csv
import time

import requests

BASE = "${BASE}"
WAIT = ${seconds}  # seconds between requests (the rate limit)


def get(url, params=None):
    """GET from the API, waiting and retrying when rate-limited."""
    while True:
        r = requests.get(url, params=params)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", WAIT)))
            continue
        r.raise_for_status()
        return r.json()


params = {"assay_type": "RNA-Seq", "sample_country": "Greece", "limit": 100, "offset": 0}
projects = []
while True:
    page = get(f"{BASE}/projects", params)
    projects += page["results"]
    print(f'{len(projects)} of {page["total"]}')
    params["offset"] += params["limit"]
    if params["offset"] >= page["total"]:
        break
    time.sleep(WAIT)

with open("projects.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["bioproject", "sra_study", "title", "organism_name", "project_release_date"])
    writer.writeheader()
    for p in projects:
        writer.writerow({k: p[k] for k in writer.fieldnames})

print("Saved", len(projects), "projects to projects.csv")`}
          />
        </Section>

        <Section id="versioning" title="Versioning">
          <Paragraph>
            All URLs start with <Text code>/v1</Text>. Changes that could break existing scripts, such as removing
            or renaming fields or parameters, will be released as a new version (<Text code>/v2</Text>) and{' '}
            <Text code>/v1</Text> will keep working. New fields or parameters may be added to <Text code>/v1</Text>,
            so scripts should ignore fields they don't know.
          </Paragraph>
        </Section>
      </main>
    </div>
  )
}
