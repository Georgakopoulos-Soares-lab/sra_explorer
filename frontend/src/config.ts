// Publication details shown on the home page. Update these once the journal version is out.
export const PUBLICATION = {
  // e.g. '10.1093/nar/gkaa000'; the home page shows "pending" while this is null.
  doi: '10.64898/2026.11.15.766670' as string | null,
  // Where the paper appeared, shown as a tag next to the DOI (e.g. 'bioRxiv preprint').
  venue: 'bioRxiv preprint' as string | null,
  // Citation, shown with a copy button when set. The title is shown in bold.
  citation: {
    authors: 'Grigoriadis D, Perdikopanis N, Chan CSY, Pavlopoulos G, Georgakopoulos-Soares I.',
    title: 'SRAscout: Semantic discovery of public sequencing data through harmonized SRA and BioProject metadata.',
    source: 'bioRxiv 2026.11.15.766670; doi: https://doi.org/10.64898/2026.11.15.766670',
  } as { authors: string; title: string; source: string } | null,
}
