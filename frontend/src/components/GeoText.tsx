import ExternalLink from './ExternalLink'

// GEO sample (GSM) and series (GSE) accessions, with any suffix joined to them
// (e.g. the run alias "GSM708662_3"): the whole token is the link text, and
// the link goes to the accession itself.
const GEO_RE = /\b(GS[EM]\d+\w*)/g

const geoUrl = (accession: string) =>
  `https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=${encodeURIComponent(accession)}`

// Shows text with any GEO accessions in it turned into links to GEO.
export default function GeoText({ text }: { text: string }) {
  const parts = text.split(GEO_RE)
  if (parts.length === 1) return <>{text}</>
  // split() with a capture group puts the matches at the odd indexes.
  return (
    <>
      {parts.map((part, i) =>
        i % 2 ? (
          <ExternalLink key={i} href={geoUrl(part.match(/GS[EM]\d+/)![0])} mono={false}>
            {part}
          </ExternalLink>
        ) : (
          part
        ),
      )}
    </>
  )
}
