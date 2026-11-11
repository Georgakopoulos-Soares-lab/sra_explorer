import { ArrowRightOutlined, BulbOutlined } from '@ant-design/icons'
import { Anchor, Button, Card, Collapse, Grid, Typography } from 'antd'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import BrandName from '../components/BrandName'

const { Title, Paragraph, Text } = Typography

// Examples that open a working search. Keep them in step with the data: each
// was checked to return results.
const EXAMPLE_TEXT = 'single-cell RNA-seq of human lung tumours'
const EXAMPLE_PMID = '42314152'
const EXAMPLE_STUDY = 'SRP567064'
const q = (params: Record<string, string | string[]>) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) for (const item of ([] as string[]).concat(v)) p.append(k, item)
  return p.toString()
}

interface Tutorial {
  key: string
  title: string
  // What the tutorial is for, in one or two sentences.
  intro: ReactNode
  steps: ReactNode[]
  tips?: ReactNode[]
  // Opens a working example.
  tryIt?: { to: string; label: string }
  // A screenshot in public/help/.
  image?: { src: string; alt: string }
}

const TUTORIALS: Tutorial[] = [
  {
    key: 'describe',
    title: 'Find datasets by describing them',
    intro: (
      <>
        Write what you are looking for in your own words, as you would tell a colleague. The search compares the meaning of
        your text with every project's title and description, so it also finds projects that use other words, and combines
        that with a classic search for your exact words.
      </>
    ),
    steps: [
      <>
        Open <Link to="/search">Semantic search</Link> and type a description in the search box, for example{' '}
        <Text code>{EXAMPLE_TEXT}</Text>. A whole sentence or an abstract works better than one or two keywords.
      </>,
      <>
        Press <Text keyboard>Enter</Text> or click <b>Search</b>. Above the box, <b>Describe the data</b> lights up to show the
        text is searched by meaning.
      </>,
      <>
        Results come most relevant first. Projects that contain all your words and are close in meaning rank highest. Click a
        column header (Experiments, Publications, Released) to sort differently.
      </>,
    ],
    tips: [
      <>Name the organism, tissue or cell type and the assay: "ATAC-seq of mouse hematopoietic stem cells" beats "chromatin".</>,
      <>
        Combine a description with filters (next tutorials) to keep its ranking but only, say, human RNA-Seq projects released
        since 2022.
      </>,
    ],
    tryIt: { to: `/search?${q({ q: EXAMPLE_TEXT })}`, label: 'Run this search' },
    image: { src: '/help/search.png', alt: 'Search results for a description, with tags under each title' },
  },
  {
    key: 'accession',
    title: 'Look up accessions or a paper',
    intro: <>The same search box takes BioProject and SRA study accessions, and the DOI or PubMed ID of a paper.</>,
    steps: [
      <>
        <b>Accessions:</b> paste one or more BioProject (PRJNA, PRJEB, PRJDB) or SRA study (SRP, ERP, DRP) accessions, separated
        by spaces or commas, for example <Text code>PRJNA169753 SRP567064</Text>. Only those projects are shown.
      </>,
      <>
        <b>A paper:</b> paste its DOI (<Text code>10.1038/…</Text> or a doi.org link) or PubMed ID. <BrandName /> fetches the
        paper's title and abstract and searches with them, so you find the paper's own data and data on the same subject.
        The paper's title is shown above the results.
      </>,
      <>The highlighted <b>Search mode</b> above the box confirms how your text was understood.</>,
    ],
    tryIt: { to: `/search?${q({ q: EXAMPLE_PMID })}`, label: `Search with PubMed ID ${EXAMPLE_PMID}` },
  },
  {
    key: 'filters',
    title: 'Narrow down with filters',
    intro: (
      <>
        The filter panel on the left narrows the results by organism, sample, how the data was sequenced, submitter, size and
        publications. Filters work with or without a text search.
      </>
    ),
    steps: [
      <>
        Open a section of the panel, for example <b>Organism, samples and sequencing</b>, and choose values. Long lists
        (organism, tissue, cell type, …) are searched as you type.
      </>,
      <>
        Every filter only offers values found in the projects matching your other filters, with the number of projects for
        each. You see what is available before you choose, and never reach an empty result by accident. (The lists follow the
        filters, not the search text.)
      </>,
      <>
        Results update at once. The chosen values appear as chips above the results; click a chip's × to remove it, or{' '}
        <b>Clear all</b>.
      </>,
    ],
    tips: [
      <>
        Several values in one filter match any of them (RNA-Seq <i>or</i> ChIP-Seq). Different filters must all match.
      </>,
      <>
        Sequencing filters (assay type, instrument, library) must all match the <i>same run</i>, so "RNA-Seq" + "PAIRED" finds
        projects with paired-end RNA-Seq runs, not projects with some RNA-Seq and some paired runs.
      </>,
      <>
        Sample filters (cell line, tissue, disease, …) come from the attributes submitters gave their samples, cleaned so
        different spellings match. Submitters often leave them out, so they find fewer projects than a text search.
      </>,
    ],
    tryIt: {
      to: `/search?${q({ q: EXAMPLE_TEXT, assay_type: 'RNA-Seq', release_from: '2022-01-01' })}`,
      label: 'The lung tumour search, RNA-Seq only, since 2022',
    },
    image: { src: '/help/filters.png', alt: 'The filter panel with values and project counts' },
  },
  {
    key: 'tags',
    title: 'Use tags to refine a search',
    intro: (
      <>
        Each project is tagged with the organisms, diseases, tissues, cell types, cell lines, chemicals and environments named
        in its description. Tags let you narrow a search by what a project is about, whatever words its submitters used.
      </>
    ),
    steps: [
      <>Run any search. Each result shows its tags as grey chips under the title.</>,
      <>
        Click a tag to keep only projects with it. It is added to the <b>Tags</b> row above the results, in blue.
      </>,
      <>
        The Tags row also suggests tags common among your top results (dashed, with a +). Click one to narrow further. The
        number on each is how many of the top results have it.
      </>,
      <>
        By default a project must have <i>all</i> chosen tags. Turn on <b>Match any of the tags</b> in the Tags section of the
        filter panel to get projects with at least one, for example both <Text code>mouse</Text> and{' '}
        <Text code>Mus musculus</Text>.
      </>,
      <>
        Let the search choose the tags: turn on <b>Deep search</b> under the search box, then search. The tag words in
        your text (organisms, diseases, tissues, cell types, …) are matched with the tags of the top results and the best
        ones are added to the Tags row, marked ✦. For <Text code>{EXAMPLE_TEXT}</Text> that is{' '}
        <Text code>Homo sapiens</Text> and <Text code>lung cancer</Text>. Remove them like any tag. The switch stays on
        for your next searches; it is on by default.
      </>,
    ],
    tips: [
      <>
        Only part of the projects have tags so far, and a tag filter leaves out the others. To search everything, describe the
        data in the search box instead, or turn Deep search off.
      </>,
    ],
    tryIt: { to: `/search?${q({ q: EXAMPLE_TEXT, tag: 'T cell' })}`, label: 'The lung tumour search, with the tag T cell' },
  },
  {
    key: 'project',
    title: 'Inspect a project',
    intro: <>Every result opens in place to show what you need to decide whether the data fits.</>,
    steps: [
      <>Click a result row. It expands below.</>,
      <>
        <b>Project</b>: the full title and description, the submitting organisation and country, and the linked GEO series.
      </>,
      <>
        <b>Publications</b>: the papers linked to the project, with their titles, journals and links to PubMed or the DOI.
      </>,
      <>
        <b>Similar projects</b>: the projects whose descriptions are closest in meaning, with a similarity score. Useful for
        finding replicates, follow-ups and comparable datasets.
      </>,
      <>
        <b>Sequencing files</b>: how many runs ENA has for the study, with a button to the file list (next tutorial). The
        BioProject and SRA study accessions in the first column link to ENA and NCBI.
      </>,
    ],
    image: { src: '/help/details.png', alt: 'An expanded project with its description, publications and similar projects' },
  },
  {
    key: 'files',
    title: 'Download the sequencing files',
    intro: <>The files page lists every run of an SRA study with its FASTQ files, read live from ENA.</>,
    steps: [
      <>
        In an expanded project, click <b>View files</b>. The page opens in a new tab.
      </>,
      <>
        Each run shows its sample, library, instrument and size, and its FASTQ files with direct links. Use the filters at the
        top to keep only some runs, for example only paired-end RNA-Seq, or type part of a sample name.
      </>,
      <>
        <b>Download</b> gives the files of the runs shown as a link list (.txt), a <Text code>wget</Text> script (.sh) to fetch
        them all, or MD5 checksums to check the downloads.
      </>,
    ],
    tips: [
      <>
        Run the script with <Text code>sh {EXAMPLE_STUDY}_download.sh</Text>. <Text code>wget -c</Text> resumes interrupted
        downloads, so it is safe to run again.
      </>,
      <>Where ENA has no processed FASTQ, the files as submitted or the SRA-format file are listed, marked as such.</>,
    ],
    tryIt: { to: `/files/${EXAMPLE_STUDY}`, label: `Files of ${EXAMPLE_STUDY}` },
    image: { src: '/help/files.png', alt: 'The files page with runs, FASTQ links and the download menu' },
  },
  {
    key: 'summary',
    title: 'Summarise what a search found',
    intro: (
      <>
        Before you go through the results one by one, see what they contain overall: assays, organisms, tissues, cell types,
        countries and release years.
      </>
    ),
    steps: [
      <>
        Run a search, then click <b>Show</b> on the <b>Summary statistics</b> bar above the table.
      </>,
      <>
        The summary counts <i>everything</i> the search matches, not only the page shown, and shows the most common values of
        each as bars.
      </>,
      <>Click a value to add it as a filter. The <b>CSV</b> button downloads the counts for a report or a figure.</>,
    ],
  },
  {
    key: 'tag-explorer',
    title: 'Explore datasets through tags',
    intro: (
      <>
        The <Link to="/tags">Tag explorer</Link> starts from tags instead of a text search: combine them, see how many projects
        have them and what else those projects are about.
      </>
    ),
    steps: [
      <>
        Type a tag in <b>Find projects by tags</b>, or click one of the examples. The number of matching BioProjects appears at
        once.
      </>,
      <>
        <b>Narrow down</b> under the box suggests the tags most often found with yours, each with the number of projects you
        would get by adding it. Click one to add it.
      </>,
      <>
        The cards below show the related tags (most common, or most characteristic of these projects), their organisms and
        release years, and the latest matching projects.
      </>,
      <>
        Click <b>Show … in Search</b> to open the same projects on the search page, where you can add filters, inspect them and
        download their files.
      </>,
    ],
    tips: [
      <>
        Below the line, <b>Tag network</b> and <b>Tags that go together</b> show which tags occur on the same projects. Click
        a tag or a line to choose it.
      </>,
      <>The page address holds your tags, so you can bookmark or share a view.</>,
    ],
    tryIt: { to: `/tags?${q({ tag: ['liver', 'mouse'] })}`, label: 'Projects tagged liver and mouse' },
    image: { src: '/help/tags.png', alt: 'The Tag explorer with chosen tags, suggestions and related tags' },
  },
  {
    key: 'statistics',
    title: 'Read the database statistics',
    intro: (
      <>
        The <Link to="/statistics">Statistics</Link> page shows what the database covers: how it has grown, the assays,
        platforms and instruments behind the data, where it comes from and how much is published.
      </>
    ),
    steps: [
      <>Each chart has a <b>Table</b> view with every number and a <b>CSV</b> download.</>,
      <>
        Charts over time have toggles (projects, studies or runs; per year or cumulative). Click a legend entry to show or hide
        a line.
      </>,
      <>Click a value name, where it is a link, to search for those projects.</>,
    ],
  },
  {
    key: 'api',
    title: 'Search from a script',
    intro: (
      <>
        Everything the filters do is available as a public API that needs no key, for pipelines and notebooks. The{' '}
        <Link to="/docs/api">API documentation</Link> has every parameter and examples in Python and curl.
      </>
    ),
    steps: [
      <>
        Search with <Text code>GET /v1/projects</Text> and the same filters as the website, for example{' '}
        <Text code>?assay_type=RNA-Seq&amp;tag=liver</Text>.
      </>,
      <>
        Look up projects by accession with <Text code>GET /v1/projects/PRJNA169753</Text>, and find a filter's values with{' '}
        <Text code>GET /v1/filters/organism?q=homo</Text>.
      </>,
      <>The API allows one request every 5 seconds per address; page through large results with limit and offset.</>,
    ],
    tryIt: { to: '/docs/api', label: 'API documentation' },
  },
]

const FAQ: { q: string; a: ReactNode }[] = [
  {
    q: 'How can I share or save a search?',
    a: (
      <>
        Copy the address from the browser. It holds the search text, filters, tags, sort and page, so it opens the same search
        for anyone. The browser's back button undoes your last change.
      </>
    ),
  },
  {
    q: 'Why does a text search find projects that do not contain my words?',
    a: (
      <>
        The search compares meaning, not only words, so a project on "hepatocellular carcinoma" is found by "liver cancer".
        Projects that contain all your words rank higher. If a result seems off, add a filter or more detail to your text.
      </>
    ),
  },
  {
    q: 'What does Deep search do?',
    a: (
      <>
        It makes a text search more precise by adding tags to it. Your text is cut into phrases, which are matched with the
        tags of the search's top results (up to 2,000): the same words (after case, plurals and spellings are evened out), a common
        organism name for its species (human → Homo sapiens), or a close meaning by the same language model that powers the
        search (lung tumour → lung cancer). The best matching tags are added one by one, most characteristic of the results
        first, as long as enough results keep all of them. Only tagged projects can match a tag, so results are fewer; turn it off
        to search every project. The API answer behind it (<Text code>/search/query-tags</Text>) lists every tag considered
        and why it was or wasn't added.
      </>
    ),
  },
  {
    q: 'Why do I get fewer results with a tag or sample filter?',
    a: (
      <>
        Tags exist for part of the projects so far, and sample attributes only where submitters gave them. Those filters leave
        out projects without them. A text search covers every project.
      </>
    ),
  },
  {
    q: 'How current is the data?',
    a: (
      <>
        The database is updated every week from NCBI SRA, NCBI BioProject and ENA: new runs and projects are added, then
        indexed and tagged. The <Link to="/statistics">Statistics</Link> page shows the latest release date included. File
        lists are read live from ENA.
      </>
    ),
  },
  {
    q: 'What is the difference between a BioProject, an SRA study and a run?',
    a: (
      <>
        A <b>BioProject</b> (PRJNA…) describes a research project. Its sequencing data is submitted as one or more{' '}
        <b>SRA studies</b> (SRP…), each holding <b>runs</b> (SRR…): one sequencing run of one sample. Results list each BioProject
        and SRA study pair.
      </>
    ),
  },
  {
    q: 'How are tags made?',
    a: (
      <>
        A biomedical language model finds organisms, diseases, tissues, cell types, cell lines, chemicals and environments in
        each project's title and description; the tags are then cleaned and filtered for relevance. The{' '}
        <Link to="/tags">Tag explorer</Link> explains the method step by step, with an example.
      </>
    ),
  },
]

function Screenshot({ src, alt }: { src: string; alt: string }) {
  const [failed, setFailed] = useState(false)
  if (failed) return null
  return (
    <a href={src} target="_blank" rel="noreferrer" className="block">
      <img
        src={src}
        alt={alt}
        loading="lazy"
        onError={() => setFailed(true)}
        className="mx-auto block h-auto max-w-full rounded-md border border-solid border-gray-200 shadow-sm"
      />
    </a>
  )
}

function TutorialCard({ t, n }: { t: Tutorial; n: number }) {
  return (
    <section id={t.key} className="scroll-mt-6">
      <Card>
        <div className="mb-2 flex items-center gap-3">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-semibold text-white">
            {n}
          </span>
          <Title level={3} className="!m-0">
            {t.title}
          </Title>
        </div>
        <Paragraph type="secondary">{t.intro}</Paragraph>
        <div className={t.image ? 'grid grid-cols-1 gap-6 xl:grid-cols-2' : ''}>
          <div>
            <ol className="m-0 space-y-2 pl-5">
              {t.steps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
            {t.tips && (
              <div className="mt-4 rounded-md bg-amber-50 px-4 py-3">
                <div className="mb-1 flex items-center gap-2 font-medium text-amber-800">
                  <BulbOutlined /> Tips
                </div>
                <ul className="m-0 space-y-1 pl-5 text-sm text-gray-700">
                  {t.tips.map((tip, i) => (
                    <li key={i}>{tip}</li>
                  ))}
                </ul>
              </div>
            )}
            {t.tryIt && (
              <Link to={t.tryIt.to} className="mt-4 inline-block max-w-full">
                {/* Long labels wrap instead of widening the page on phones. */}
                <Button type="primary" icon={<ArrowRightOutlined />} iconPlacement="end" className="!h-auto max-w-full !whitespace-normal py-1 text-left">
                  Try it: {t.tryIt.label}
                </Button>
              </Link>
            )}
          </div>
          {t.image && <Screenshot {...t.image} />}
        </div>
      </Card>
    </section>
  )
}

export default function HelpPage() {
  const isDesktop = Grid.useBreakpoint().lg ?? true
  const sections = [
    { key: 'start', title: 'Quick start' },
    ...TUTORIALS.map((t, i) => ({ key: t.key, title: `${i + 1}. ${t.title}` })),
    { key: 'faq', title: 'Questions' },
  ]

  return (
    <div className="mx-auto flex max-w-[1400px] gap-8 px-4 py-8">
      {isDesktop && (
        <aside className="w-64 shrink-0">
          <div className="sticky top-6">
            <Anchor
              offsetTop={24}
              items={sections.map((s) => ({ key: s.key, href: `#${s.key}`, title: <span className="text-sm">{s.title}</span> }))}
            />
          </div>
        </aside>
      )}

      <main className="min-w-0 flex-1">
        <Title level={2} className="!mb-1">
          Help and tutorials
        </Title>
        <Paragraph type="secondary" className="max-w-3xl">
          How to find, inspect and download sequencing datasets with <BrandName />. Each tutorial takes a few minutes and ends
          with a link that runs its example.
        </Paragraph>

        <section id="start" className="mb-8 scroll-mt-6">
          <Title level={3}>Quick start</Title>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {[
              { title: 'Search', text: 'Describe the data you need, or paste accessions, a DOI or a PubMed ID.', to: '#describe' },
              { title: 'Narrow down', text: 'Add filters and tags. Each shows what is available, with counts.', to: '#filters' },
              { title: 'Get the data', text: 'Open a project for its details, then download its FASTQ files.', to: '#files' },
            ].map((s, i) => (
              <a key={s.title} href={s.to} className="block text-inherit hover:no-underline">
                <Card size="small" hoverable className="h-full">
                  <div className="mb-1 flex items-center gap-2 font-semibold">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-600 text-xs text-white">{i + 1}</span>
                    {s.title}
                  </div>
                  <Text type="secondary">{s.text}</Text>
                </Card>
              </a>
            ))}
          </div>
        </section>

        <div className="flex flex-col gap-6">
          {TUTORIALS.map((t, i) => (
            <TutorialCard key={t.key} t={t} n={i + 1} />
          ))}
        </div>

        <section id="faq" className="mt-10 scroll-mt-6">
          <Title level={3}>Questions</Title>
          <Collapse items={FAQ.map((f, i) => ({ key: String(i), label: f.q, children: <div>{f.a}</div> }))} />
          <Paragraph type="secondary" className="mt-6">
            Something missing or not working? Let us know through the project's{' '}
            <a href="https://github.com/Georgakopoulos-Soares-lab/sra_explorer/issues" target="_blank" rel="noreferrer">
              GitHub issues
            </a>
            .
          </Paragraph>
        </section>
      </main>
    </div>
  )
}
