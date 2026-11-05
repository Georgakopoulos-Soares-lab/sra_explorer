"""Resolves a paper reference typed in the search box (a DOI or a PubMed ID)
to the paper's title and abstract, so the search runs exactly as if that text
had been pasted.

PubMed (NCBI E-utilities) is asked first: it has abstracts for nearly all
biomedical papers, and finds a DOI through the [doi] field. Crossref is the
fallback for DOIs PubMed doesn't know; it often has the title only.

Lookups go over the network (10 s timeout) and are cached per reference, so
a search's several requests (results, tag suggestions, summary) and the
page's own lookup share one fetch.
"""

import functools
import html
import json
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10
USER_AGENT = "SRAscout/1.0 (search by publication)"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CROSSREF = "https://api.crossref.org/works/"

# Keep in sync with parseReference in frontend/src/search/reference.ts.
# A DOI, optionally as a doi.org URL or with a "doi:" prefix.
DOI_RE = re.compile(r"^(?:(?:https?://)?(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/\S+)$", re.IGNORECASE)
# A PubMed ID: bare digits, "PMID: 123", or a pubmed.ncbi.nlm.nih.gov URL.
PMID_RE = re.compile(r"^(?:(?:https?://)?pubmed\.ncbi\.nlm\.nih\.gov/|pmid:?\s*)?(\d{1,8})/?$", re.IGNORECASE)


class LookupError(Exception):
    """The lookup service couldn't be reached or gave an unusable answer."""


@dataclass(frozen=True)
class Publication:
    kind: str  # "doi" or "pmid": what the user typed
    id: str
    title: str
    abstract: str
    pmid: Optional[str]
    doi: Optional[str]
    source: str  # "pubmed" or "crossref"

    @property
    def search_text(self) -> str:
        """Title and abstract joined the way create_embeddings.py joins a project's fields."""
        return ". ".join(p for p in (self.title.rstrip(". "), self.abstract) if p)

    @property
    def url(self) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/" if self.pmid else f"https://doi.org/{self.doi}"


def parse_reference(text: str) -> Optional[tuple[str, str]]:
    """("doi", id) or ("pmid", id) when the whole text is one reference, else None."""
    text = text.strip()
    m = DOI_RE.match(text)
    if m:
        return "doi", m.group(1).rstrip(".,;")
    m = PMID_RE.match(text)
    if m:
        return "pmid", m.group(1).lstrip("0") or "0"
    return None


def label(kind: str, id: str) -> str:
    return f"DOI {id}" if kind == "doi" else f"PubMed ID {id}"


_lock = threading.Lock()


def resolve(kind: str, id: str) -> Optional[Publication]:
    """The paper, or None when no service knows the reference.

    Raises LookupError when a service can't be reached. Only successful
    lookups are cached; the lock makes concurrent requests for the same
    paper wait for one fetch instead of each fetching.
    """
    with _lock:
        return _resolve_cached(kind, id)


@functools.lru_cache(maxsize=256)
def _resolve_cached(kind: str, id: str) -> Optional[Publication]:
    if kind == "pmid":
        return _from_pubmed(kind, id, id)
    # PubMed's search backend fails now and then; Crossref then still answers.
    try:
        pmid = _pubmed_id_for_doi(id)
        pub = _from_pubmed(kind, id, pmid) if pmid else None
    except LookupError as e:
        logger.warning("PubMed lookup of DOI %s failed, trying Crossref: %s", id, e)
        pub = None
    return pub or _from_crossref(id)


def _get(url: str, params: dict) -> bytes:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}" if query else url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return b""
        raise LookupError(f"The publication lookup failed ({e.code} from {urllib.parse.urlsplit(url).netloc}).")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("Publication lookup failed for %s: %s", url, e)
        raise LookupError("The publication lookup service could not be reached. Try again in a moment.")


def _pubmed_id_for_doi(doi: str) -> Optional[str]:
    data = _get(f"{EUTILS}/esearch.fcgi", {"db": "pubmed", "term": f"{doi}[doi]", "retmode": "json", "tool": "SRAscout"})
    try:
        ids = json.loads(data)["esearchresult"]["idlist"] if data else []
    except (ValueError, KeyError, TypeError):
        raise LookupError("PubMed gave an unexpected answer.")
    return ids[0] if ids else None


def _from_pubmed(kind: str, id: str, pmid: str) -> Optional[Publication]:
    data = _get(f"{EUTILS}/efetch.fcgi", {"db": "pubmed", "id": pmid, "retmode": "xml", "tool": "SRAscout"})
    if not data:
        return None
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise LookupError("PubMed gave an unexpected answer.")
    article = root.find("./PubmedArticle/MedlineCitation/Article")
    if article is None:
        return None
    title = _text(article.find("ArticleTitle"))
    # Structured abstracts have labelled parts (BACKGROUND, METHODS, ...).
    parts = []
    for part in article.findall("Abstract/AbstractText"):
        body = _text(part)
        if body:
            parts.append(f"{part.get('Label')}: {body}" if part.get("Label") else body)
    doi = root.findtext("./PubmedArticle/PubmedData/ArticleIdList/ArticleId[@IdType='doi']")
    if not title and not parts:
        return None
    return Publication(kind, id, title, " ".join(parts), pmid, (doi or (id if kind == "doi" else None)), "pubmed")


def _from_crossref(doi: str) -> Optional[Publication]:
    data = _get(CROSSREF + urllib.parse.quote(doi, safe=""), {})
    if not data:
        return None
    try:
        work = json.loads(data)["message"]
    except (ValueError, KeyError, TypeError):
        raise LookupError("Crossref gave an unexpected answer.")
    titles = work.get("title") or []
    title = _strip_tags(titles[0]) if titles else ""
    abstract = _strip_tags(work.get("abstract") or "")  # JATS XML
    if not title and not abstract:
        return None
    return Publication("doi", doi, title, abstract, None, doi, "crossref")


def _text(element: Optional[ET.Element]) -> str:
    """An element's text with inline markup (italics, sub/superscripts) flattened."""
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def _strip_tags(markup: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())
