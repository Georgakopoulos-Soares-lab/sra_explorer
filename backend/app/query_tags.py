"""Deep search (the site calls it so; "guided" in the code): the tag words in a search text, matched with the tags
of the search's own top results, for the page to add to the Tags filter.

GET /search/query-tags takes the same parameters as /search/bioprojects (q
required) and answers which tags to add, listing every tag it considered
with the words it matched, how, and why it was or wasn't taken. The page
then runs the ordinary search with those tags (tag=...), so a deep
search is a plain search whose tags were chosen here; the two requests
reproduce it from the command line.

How the tags are chosen (docs/search.md, "Deep search"):

1. The text (q, or the paper's title and abstract for a DOI or PubMed ID) is
   cut into phrases: every run of 1 to MAX_PHRASE_WORDS words among the first
   MAX_WORDS, except runs that start or end with a stop word.
2. The pool is the search's top POOL_SIZE rows with the current filters (the
   same list /search/tag-summary reads), and a tag's count is the number of
   pool projects that have it. Tags on fewer than MIN_COUNT pool projects are
   ignored: a tag the results don't share is no use as a filter, however well
   it matches the text.
3. A phrase matches a pool tag when the two are the same after normalisation
   (case, hyphens, plurals, British spellings: "lung tumours" is "lung
   tumor"), when the phrase is a common organism name and the tag its species
   (ORGANISM_ALIASES: "human" is "Homo sapiens"), or when the two are
   similar: a BioBERT cosine similarity of at least SIMILAR_MIN and a word in
   common or a known head word (HEAD_WORDS: tumor is cancer, renal is
   kidney), or of at least SIMILAR_MIN_UNRELATED without one. Pairs that
   differ only in a qualifier ("type 1" and "type 2 diabetes", "T cell" and
   "B cell") never match. A phrase that is itself a tag (or an alias) only
   matches that way: the words typed are the safest choice.
4. Each match is scored by its tag's count times the log of its lift, the
   tag's share of the pool's tagged projects over its share of all tagged
   projects: tags the results share far more than usual come first, and the
   common tags a text mentions ("Homo sapiens") still score by their count.
   An exact match inside a longer exact match of comparable count gives way
   to it ("soil" to "soil microbiome"). Matches are taken best first; one is
   skipped when its words were already used by a taken tag, when its tag is
   a spelling of one already taken or names the same organism ("silkworm"
   after "Bombyx mori"), and, since a project must have every chosen tag,
   when fewer than the floor of the pool's tagged projects would keep all
   the tags taken so far. At most MAX_TAGS tags are taken.

Only projects with tags can match a tag filter (about a quarter so far), so
a deep search returns fewer, more precise results; the response says
how many of the pool had no tags. Tag and phrase vectors are cached across
requests, so the extra time is mostly the embedding of a text's new phrases:
about a second for an abstract, much less for a sentence.
"""

import logging
import math
import os
import re
import threading
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from typing import Annotated, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import embeddings, schemas, search
from .database import engine, get_db
from .search import B, G, SiteSearchFilters, query_text, top_rows

router = APIRouter(prefix="/search", tags=["search"])
logger = logging.getLogger(__name__)

# The top results examined, as in search.tag_summary.
POOL_SIZE = 2000
POOL_TIMEOUT_MS = 20000
# A tag must be on this many pool projects to be considered.
MIN_COUNT = 3
# Words of the text that are read (the tagging pipeline reads the same).
MAX_WORDS = 300
# Longest phrase looked up as it is; longest phrase compared by embedding
# (tags are mostly one or two words, and embedding is the slow part).
MAX_PHRASE_WORDS = 5
MAX_SIMILAR_WORDS = 3
# Cosine similarity for a phrase to count as the same thing as a tag, with
# and without a word (or head word) in common. On BioBERT: lung tumor~lung
# cancer 0.83, kidney~renal 0.83, hepatocellular carcinoma~liver cancer 0.77,
# but human lung~lung 0.72, lung~lung cancer 0.64, breast cancer~lung cancer 0.55.
SIMILAR_MIN = float(os.getenv("GUIDED_SIMILAR_MIN", "0.75"))
SIMILAR_MIN_UNRELATED = float(os.getenv("GUIDED_SIMILAR_MIN_UNRELATED", "0.85"))
# An exact match gives way to a longer one around it when the longer tag's
# count is at least this share of its own ("soil" to "soil microbiome").
CONTAINING_MIN_SHARE = 0.5
# Tags added at most, and the fewest tagged pool projects that must keep all
# of them: the larger of a number and a share of the pool's tagged projects.
MAX_TAGS = 4
MIN_REMAINING = 5
MIN_REMAINING_SHARE = 0.02

CACHE_SECONDS = 3600
CACHE_SIZE = 500
VECTOR_CACHE_SIZE = 10000
# Tags embedded ahead of the first request, most common first.
WARM_TAGS = 5000

# Phrases can't start or end with these: function words, and words that
# describe data rather than what it is about.
STOP_WORDS = set("""
a an the of in on at to for from with without by and or nor but as is are was were be been being this that
these those it its their our we they he she his her which who whom whose what when where while than then
there here such via per into onto over under between among across within after before during both each
either neither not no also only more most less least very using used use based through towards toward
about up down out off all any some other others same further however thus hence therefore can could may
might will would should must do does did done have has had having i you your
study studies analysis analyses data dataset datasets sequencing seq profiling characterization
characterisation
""".split())

# British spelling -> American, applied inside words on both sides of a match.
SPELLINGS = [
    ("tumour", "tumor"), ("haem", "hem"), ("oestr", "estr"), ("leukaem", "leukem"), ("anaem", "anem"),
    ("aemia", "emia"), ("foet", "fet"), ("oedem", "edem"), ("paediatr", "pediatr"), ("colour", "color"),
    ("behaviour", "behavior"), ("centre", "center"), ("fibre", "fiber"), ("ageing", "aging"),
    ("diarrhoea", "diarrhea"),
    ("oesophag", "esophag"), ("gynaecol", "gynecol"), ("sulphur", "sulfur"), ("sulphate", "sulfate"),
    ("mould", "mold"), ("caesium", "cesium"), ("aluminium", "aluminum"),
]

# Common organism names -> the species as bioprojects name it. Phrases are
# matched after normalisation, so keys are lowercase, singular, no hyphens.
ORGANISM_ALIASES = {
    "human": "Homo sapiens", "patient": "Homo sapiens",
    "mouse": "Mus musculus", "murine": "Mus musculus",
    "rat": "Rattus norvegicus",
    "zebrafish": "Danio rerio",
    "fruit fly": "Drosophila melanogaster", "drosophila": "Drosophila melanogaster",
    "c elegans": "Caenorhabditis elegans",
    "yeast": "Saccharomyces cerevisiae", "budding yeast": "Saccharomyces cerevisiae",
    "fission yeast": "Schizosaccharomyces pombe",
    "e coli": "Escherichia coli",
    "arabidopsis": "Arabidopsis thaliana", "thale cress": "Arabidopsis thaliana",
    "rice": "Oryza sativa", "maize": "Zea mays", "corn": "Zea mays", "wheat": "Triticum aestivum",
    "soybean": "Glycine max", "tomato": "Solanum lycopersicum", "potato": "Solanum tuberosum",
    "barley": "Hordeum vulgare", "grapevine": "Vitis vinifera", "grape": "Vitis vinifera",
    "cotton": "Gossypium hirsutum", "tobacco": "Nicotiana tabacum", "sorghum": "Sorghum bicolor",
    "rapeseed": "Brassica napus", "cucumber": "Cucumis sativus", "apple": "Malus domestica",
    "pig": "Sus scrofa", "swine": "Sus scrofa", "porcine": "Sus scrofa",
    "chicken": "Gallus gallus", "cattle": "Bos taurus", "cow": "Bos taurus", "bovine": "Bos taurus",
    "sheep": "Ovis aries", "goat": "Capra hircus", "horse": "Equus caballus",
    "dog": "Canis lupus familiaris", "canine": "Canis lupus familiaris", "cat": "Felis catus",
    "rabbit": "Oryctolagus cuniculus", "macaque": "Macaca mulatta", "rhesus macaque": "Macaca mulatta",
    "chimpanzee": "Pan troglodytes", "honey bee": "Apis mellifera", "honeybee": "Apis mellifera",
    "silkworm": "Bombyx mori",
    "sars cov 2": "Severe acute respiratory syndrome coronavirus 2",
    "covid 19": "Severe acute respiratory syndrome coronavirus 2",
}

# Words that name the same thing as another, for the similar tier: a phrase
# and a tag count as related when a word of one maps to a word of the other.
HEAD_WORDS = {
    "tumor": "cancer", "carcinoma": "cancer", "neoplasm": "cancer", "malignancy": "cancer",
    "malignant": "cancer", "oncology": "cancer",
    "renal": "kidney", "hepatic": "liver", "cardiac": "heart", "pulmonary": "lung", "gastric": "stomach",
    "cutaneous": "skin", "dermal": "skin", "cerebral": "brain", "intestinal": "intestine", "gut": "intestine",
    "colonic": "colon", "neuronal": "neuron", "neural": "neuron", "microbial": "microbe",
    "microbiome": "microbiota", "bacterial": "bacteria", "fungal": "fungi", "viral": "virus",
    "muscular": "muscle", "osseous": "bone", "ocular": "eye", "retinal": "retina", "pancreatic": "pancreas",
    "splenic": "spleen", "vascular": "vessel", "endothelial": "endothelium", "epithelial": "epithelium",
    "embryonic": "embryo", "fetal": "fetus", "placental": "placenta", "ovarian": "ovary",
    "testicular": "testis", "prostatic": "prostate", "mammary": "breast", "uterine": "uterus",
}

IRREGULAR_PLURALS = {
    "mice": "mouse", "geese": "goose", "teeth": "tooth", "feet": "foot", "children": "child",
    "women": "woman", "men": "man", "leaves": "leaf", "calves": "calf", "lice": "louse",
    "oxen": "ox", "testes": "testis", "ovaries": "ovary", "bodies": "body", "humans": "human",
}
# Plural-looking words that must not lose their final "s".
NO_SINGULAR = (
    "ss", "us", "is", "ous", "ys", "ics", "itis", "osis", "diabetes", "herpes", "measles",
    "rabies", "scabies", "mumps", "rickets", "series", "species", "feces", "faeces",
    "pancreas", "lens", "iris", "bacteria", "fungi", "sepsis", "analysis", "aureus",
    "ans", "iens",
)
WORD = re.compile(r"[a-z0-9][a-z0-9']*")
# -ise, -ised, -ising, -isation after a consonant at the end of a word (-ize
# in American spelling); not "raised" or "praising".
ENDINGS = re.compile(r"(?<=[b-df-hj-np-tv-z])is(e|ed|ing|ation)$")
ROMAN = re.compile(r"^[ivx]+$")
QUALIFIER_WORDS = {"type", "stage", "grade", "class", "group", "phase"}


def singularise(word: str) -> str:
    """As Automations/TagWords/extract_tags.py singularises tags (keep the
    two in step)."""
    if word in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[word]
    if not word.endswith("s") or len(word) < 4 or word.endswith(NO_SINGULAR):
        return word
    if word.endswith("uses"):
        return word[:-2]
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "xes", "sses")):
        return word[:-2]
    return word[:-1]


def words_of(text: str) -> list[str]:
    """Lowercase words, hyphens and '+' split, possessives and British spellings gone."""
    text = text.lower().replace("’", "'")
    text = re.sub(r"[-_/+]", " ", text)
    out = []
    for word in WORD.findall(text):
        if word.endswith("'s"):
            word = word[:-2]
        for british, american in SPELLINGS:
            word = word.replace(british, american)
        # Only at the end of a word: "raised" is not "raized".
        word = ENDINGS.sub(lambda m: m.group(0).replace("is", "iz", 1), word)
        if word:
            out.append(word)
    return out


def normalise(phrase: str) -> str:
    """The form phrases and tags are compared in: words_of with the last word
    singular, the tagging pipeline's dedup key."""
    words = words_of(phrase)
    if words:
        words[-1] = singularise(words[-1])
    return " ".join(words)


def concept(tag: str) -> str:
    """What a tag names, so that two spellings or a common name and its
    species count as one: the normalised species for an organism alias."""
    key = normalise(tag)
    species = ORGANISM_ALIASES.get(key)
    return normalise(species) if species else key


def same_concept(a: str, b: str) -> bool:
    """Whether two concept keys name the same thing: the same key, or a
    species and its abbreviated binomial ("s pombe", "schizosaccharomyces pombe")."""
    if a == b:
        return True
    wa, wb = a.split(), b.split()
    if len(wa) == 2 and len(wb) == 2 and wa[1] == wb[1]:
        return (len(wa[0]) == 1 and wb[0].startswith(wa[0])) or (len(wb[0]) == 1 and wa[0].startswith(wb[0]))
    return False


@dataclass(frozen=True)
class Phrase:
    start: int
    end: int  # exclusive
    key: str  # normalised

    @property
    def words(self) -> int:
        return self.end - self.start


def phrases_of(text: str) -> tuple[int, list[Phrase]]:
    """(words read, the distinct phrases of the text at their first occurrence)."""
    words = words_of(text)[:MAX_WORDS]
    seen = set()
    out = []
    for n in range(1, MAX_PHRASE_WORDS + 1):
        for i in range(len(words) - n + 1):
            run = words[i:i + n]
            if run[0] in STOP_WORDS or run[-1] in STOP_WORDS or not any(c.isalpha() for w in run for c in w):
                continue
            key = " ".join(run[:-1] + [singularise(run[-1])])
            if key not in seen:
                seen.add(key)
                out.append(Phrase(i, i + n, key))
    return len(words), out


def is_qualifier(word: str) -> bool:
    return len(word) == 1 or any(c.isdigit() for c in word) or ROMAN.match(word) is not None or word in QUALIFIER_WORDS


def content_heads(phrase: str) -> set[str]:
    words = {w for w in phrase.split() if w not in STOP_WORDS and len(w) > 1}
    return {HEAD_WORDS.get(w, w) for w in words} | {HEAD_WORDS.get(singularise(w), singularise(w)) for w in words}


def related(a: str, b: str) -> Optional[bool]:
    """Whether two normalised phrases name the same thing, as far as their
    words say: False when they differ only in qualifiers (never the same
    thing), True with a word or head word in common, None otherwise."""
    wa, wb = set(a.split()), set(b.split())
    only_a, only_b = wa - wb, wb - wa
    if only_a and only_b and all(is_qualifier(w) for w in only_a | only_b):
        return False
    return True if content_heads(a) & content_heads(b) else None


# Unit vectors of tags and phrases, kept across requests: the common tags of
# a field and the words of its texts recur. float16: 10,000 of them is 15 MB.
_vectors: "OrderedDict[str, np.ndarray]" = OrderedDict()
_vectors_lock = threading.Lock()


def vectors_of(texts: list[str]) -> np.ndarray:
    """(n, dim) unit vectors of the texts; new texts are embedded in one batch.
    Least recently used entries go first; the vectors of this call are taken
    out of the cache under the lock, so a concurrent eviction can't lose them."""
    if not texts:
        return np.zeros((0, embeddings.EMBEDDING_DIM), dtype=np.float32)
    with _vectors_lock:
        found = {}
        for t in dict.fromkeys(texts):
            if t in _vectors:
                _vectors.move_to_end(t)
                found[t] = _vectors[t]
    missing = [t for t in dict.fromkeys(texts) if t not in found]
    if missing:
        model = embeddings.get_model()
        with embeddings.encode_lock:
            new = model.encode(missing, batch_size=64, normalize_embeddings=True, convert_to_numpy=True,
                               show_progress_bar=False)
        with _vectors_lock:
            for t, v in zip(missing, new):
                found[t] = _vectors[t] = v.astype(np.float16)
            while len(_vectors) > VECTOR_CACHE_SIZE:
                _vectors.popitem(last=False)
    return np.stack([found[t] for t in texts]).astype(np.float32)


def warm() -> None:
    """Embeds the most common tags ahead of the first request; run in a
    background thread at startup, after the model is loaded. In small
    batches, so a search arriving meanwhile only waits for one."""
    try:
        tags = [t for t, _, _ in search.tag_values()[:WARM_TAGS]]
        for i in range(0, len(tags), 256):
            vectors_of(tags[i:i + 256])
    except Exception:
        logger.exception("Could not embed the common tags ahead of time")


_tagged: tuple[float, int] = (0, 0)


def tagged_projects() -> int:
    """How many projects have tags, for the lift; cached for an hour."""
    global _tagged
    if _tagged[0] > time.monotonic():
        return _tagged[1]
    with engine.connect() as conn:
        n = conn.scalar(text("SELECT count(*) FROM bioproject_tags WHERE tags <> ''")) or 0
    _tagged = (time.monotonic() + CACHE_SECONDS, n)
    return n


def pool_of(db: Session, filters: SiteSearchFilters) -> tuple[int, int, dict[str, set[str]]]:
    """The search's top results: (projects, projects with tags, tag -> the
    pool projects that have it)."""
    top = top_rows(db, filters, POOL_SIZE, B.bioproject)
    projects: set[str] = set()
    tagged: set[str] = set()
    by_tag: dict[str, set[str]] = defaultdict(set)
    db.execute(text(f"SET LOCAL statement_timeout = {POOL_TIMEOUT_MS}"))
    rows = db.execute(select(top.c.bioproject, G.tags).outerjoin(G, G.bioproject == top.c.bioproject))
    for bioproject, tags in rows:  # a project appears once per SRA study
        projects.add(bioproject)
        if tags:
            tagged.add(bioproject)
            for tag in set(tags.split("; ")):
                if tag:
                    by_tag[tag].add(bioproject)
    return len(projects), len(tagged), by_tag


@dataclass
class Match:
    tag: str
    phrase: Phrase
    how: str  # exact, alias or similar
    similarity: float


HOW_ORDER = {"exact": 0, "alias": 1, "similar": 2}


def matches_of(phrases: list[Phrase], tags: list[str]) -> list[Match]:
    """Every (phrase, tag) pair that matches, as in step 3."""
    by_key: dict[str, list[str]] = defaultdict(list)
    for tag in tags:
        by_key[normalise(tag)].append(tag)
    out = []
    for phrase in phrases:
        for tag in by_key.get(phrase.key, []):
            out.append(Match(tag, phrase, "exact", 1.0))
        species = ORGANISM_ALIASES.get(phrase.key)
        for tag in by_key.get(normalise(species), []) if species else []:
            out.append(Match(tag, phrase, "alias", 1.0))
    exact = {m.phrase.key for m in out}
    short = [p for p in phrases if p.words <= MAX_SIMILAR_WORDS and p.key not in exact]
    if short and tags:
        try:
            similarity = vectors_of([p.key for p in short]) @ vectors_of(tags).T
        except Exception:
            logger.exception("Could not embed the phrases; using exact matches only")
            return out
        keys = [normalise(t) for t in tags]
        for i, j in zip(*np.nonzero(similarity >= SIMILAR_MIN)):
            kinship = related(short[i].key, keys[j])
            if kinship is True or (kinship is None and similarity[i, j] >= SIMILAR_MIN_UNRELATED):
                out.append(Match(tags[j], short[i], "similar", float(similarity[i, j])))
    return out


def choose(
    matches: list[Match],
    by_tag: dict[str, set[str]],
    corpus: dict[str, int],
    tagged: int,
    corpus_tagged: int,
    chosen_tags: list[str],
    labels: dict[str, Optional[str]],
) -> tuple[list[str], list[dict], int]:
    """Step 4: (the tags selected, every tag considered with its outcome,
    the floor). Pure, so it can be tested without the database."""
    count = lambda tag: len(by_tag[tag])

    def score(m: Match) -> float:
        share = count(m.tag) / max(tagged, 1)
        corpus_share = max(corpus.get(m.tag, 0), count(m.tag)) / max(corpus_tagged, 1)
        return count(m.tag) * math.log(max(share / corpus_share, 1e-9))

    # An exact match inside a longer exact match of comparable count gives way to it.
    anchored = [m for m in matches if m.how != "similar"]

    def yields(m: Match) -> bool:
        return m.how != "similar" and any(
            o.phrase.start <= m.phrase.start and m.phrase.end <= o.phrase.end and o.phrase.words > m.phrase.words
            and count(o.tag) >= CONTAINING_MIN_SHARE * count(m.tag)
            for o in anchored
        )

    matches.sort(key=lambda m: (-score(m), HOW_ORDER[m.how], -m.similarity, m.phrase.start, m.tag))

    floor = max(MIN_REMAINING, int(MIN_REMAINING_SHARE * tagged))
    keys = {concept(t) for t in chosen_tags}
    selected: list[str] = []
    spans: list[tuple[int, int]] = []
    remaining: Optional[set[str]] = None
    rows: dict[str, dict] = {}  # each tag once: its selected match, else its first
    for m in matches:
        if m.tag in chosen_tags or m.tag in selected:
            continue
        row = {
            "value": m.tag, "count": count(m.tag), "corpus": corpus.get(m.tag, count(m.tag)),
            "group": labels.get(m.tag), "phrase": m.phrase.key, "match": m.how,
            "similarity": round(m.similarity, 3), "selected": False,
        }
        key = concept(m.tag)
        if any(same_concept(key, k) for k in keys):
            row["reason"] = "a spelling of a chosen tag" if key in keys and key == normalise(m.tag) else "names the same organism as a chosen tag"
        elif yields(m):
            row["reason"] = "its words are part of a longer match"
        elif any(m.phrase.start < e and s < m.phrase.end for s, e in spans):
            row["reason"] = "its words already matched a chosen tag"
        elif len(selected) >= MAX_TAGS:
            row["reason"] = f"at most {MAX_TAGS} tags are added"
        else:
            left = by_tag[m.tag] if remaining is None else remaining & by_tag[m.tag]
            row["remaining"] = len(left)
            if len(left) < floor:
                row["reason"] = "too few results would keep every tag"
            else:
                row["selected"] = True
                selected.append(m.tag)
                spans.append((m.phrase.start, m.phrase.end))
                keys.add(key)
                remaining = left
        if row["selected"] or m.tag not in rows:
            rows[m.tag] = row
    return selected, list(rows.values()), floor


_cache: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()


def query_tags(db: Session, filters: SiteSearchFilters) -> dict:
    q = (filters.q or "").strip()
    if not q:
        raise HTTPException(status_code=422, detail="q is required.")
    if filters.tag_any:
        raise HTTPException(
            status_code=422,
            detail='Deep search needs every chosen tag to match; turn off "Match any of the tags".',
        )
    key = filters.model_dump_json(exclude={"sort", "limit", "offset", "guided"})
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    started = time.perf_counter()

    text_ = query_text(q)
    words, phrases = phrases_of(text_)
    try:
        pool, tagged, by_tag = pool_of(db, filters)
    except Exception as e:
        if "statement timeout" in str(e):
            raise HTTPException(status_code=503, detail="The search is too slow to guide by tags right now.")
        raise
    tags = sorted((t for t, s in by_tag.items() if len(s) >= MIN_COUNT), key=lambda t: (-len(by_tag[t]), t))
    matches = matches_of(phrases, tags)
    selected, rows, floor = choose(
        matches, by_tag, search.tag_counts(), tagged, tagged_projects(), filters.tag, search.tag_labels(),
    )
    result = {
        "text": text_[:200], "words": words, "pool": pool, "tagged": tagged, "untagged": pool - tagged,
        "floor": floor, "tags": rows, "selected": selected,
    }
    logger.info(
        "Deep search: %d words, %d phrases, %d pool tags, %d matches, selected %s in %.2f s",
        words, len(phrases), len(tags), len(matches), selected, time.perf_counter() - started,
    )
    _cache[key] = (time.monotonic() + CACHE_SECONDS, result)
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return result


def clear_cache() -> None:
    """After the data changed (search.clear_value_caches)."""
    global _tagged
    _cache.clear()
    _tagged = (0, 0)


@router.get("/query-tags", response_model=schemas.QueryTags)
def query_tags_endpoint(
    filters: Annotated[SiteSearchFilters, Query()],
    db: Session = Depends(get_db),
):
    """The tags a deep search adds: the tag words found in the search
    text, matched with the tags of the search's top results. Takes the same
    parameters as /search/bioprojects; q is required, and tag_any must be
    off. Every tag considered is listed with the words it matched, how, and
    why it was or wasn't selected, so the choice can be checked."""
    return query_tags(db, filters)
