import { Typography } from 'antd'
import ExternalLink from '../components/ExternalLink'
import type { Publication } from './parsePublications'

export default function Publications({ items }: { items: Publication[] }) {
  return (
    <ol className="m-0 flex list-decimal flex-col gap-2 pl-5">
      {items.map((pub, i) => (
        <li key={i}>
          {pub.title && <div>{pub.title}</div>}
          <div className="flex flex-wrap items-center gap-x-3 text-sm">
            {pub.citation && <Typography.Text type="secondary">{pub.citation}</Typography.Text>}
            {pub.pmid && (
              <ExternalLink href={`https://pubmed.ncbi.nlm.nih.gov/${pub.pmid}/`} mono={false}>
                PubMed {pub.pmid}
              </ExternalLink>
            )}
            {pub.pmc && (
              <ExternalLink href={`https://pmc.ncbi.nlm.nih.gov/articles/${pub.pmc}/`} mono={false}>
                {pub.pmc}
              </ExternalLink>
            )}
            {pub.doi && (
              <ExternalLink href={`https://doi.org/${pub.doi}`} mono={false}>
                DOI {pub.doi}
              </ExternalLink>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}
