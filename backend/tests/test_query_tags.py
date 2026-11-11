"""Tests of the deep search's pure parts (backend/app/query_tags.py):
no database or model needed. Run from backend/:

    .venv/bin/python -m unittest tests.test_query_tags
"""

import unittest
from unittest import mock

import numpy as np

from app import query_tags as qt
from app.query_tags import Match, Phrase


def pool(**projects_by_tag: list[str]) -> dict[str, set[str]]:
    return {tag: set(projects) for tag, projects in projects_by_tag.items()}


class NormaliseTest(unittest.TestCase):
    def test_case_hyphens_plurals_spellings(self):
        self.assertEqual(qt.normalise("Lung Tumours"), "lung tumor")
        self.assertEqual(qt.normalise("T-cells"), "t cell")
        self.assertEqual(qt.normalise("Alzheimer's disease"), "alzheimer disease")
        self.assertEqual(qt.normalise("mice"), "mouse")
        self.assertEqual(qt.normalise("haematopoietic stem cells"), "hematopoietic stem cell")
        self.assertEqual(qt.normalise("SARS-CoV-2"), "sars cov 2")

    def test_words_that_keep_their_s(self):
        for word in ("diabetes", "species", "pancreas", "analysis", "Homo sapiens"):
            self.assertEqual(qt.normalise(word), word.lower())

    def test_markers_and_endings(self):
        self.assertEqual(qt.normalise("CD4+ T cells"), qt.normalise("CD4 T cells"))
        self.assertEqual(qt.normalise("raised"), "raised")
        self.assertEqual(qt.normalise("characterised"), "characterized")
        self.assertEqual(qt.normalise("organisation"), "organization")

    def test_alphanumeric_words_make_phrases(self):
        _, phrases = qt.phrases_of("MCF7 breast cancer and p53")
        keys = {p.key for p in phrases}
        self.assertIn("mcf7", keys)
        self.assertIn("p53", keys)
        _, phrases = qt.phrases_of("12 34")
        self.assertEqual(phrases, [])

    def test_only_the_last_word_is_singularised(self):
        self.assertEqual(qt.normalise("tumours and cells"), "tumors and cell")


class PhrasesTest(unittest.TestCase):
    def test_runs_of_words_not_bounded_by_stop_words(self):
        words, phrases = qt.phrases_of("single-cell RNA-seq of human lung tumours")
        keys = {p.key for p in phrases}
        self.assertEqual(words, 8)
        for key in ("single cell", "human", "lung tumor", "human lung tumor", "single cell rna"):
            self.assertIn(key, keys)
        # "seq" and "of" are stop words, so no phrase starts or ends with them.
        for key in ("of human", "seq of", "rna seq"):
            self.assertNotIn(key, keys)

    def test_spans_and_first_occurrence(self):
        _, phrases = qt.phrases_of("lung cancer and lung")
        lung = [p for p in phrases if p.key == "lung"]
        self.assertEqual(lung, [Phrase(0, 1, "lung")])
        self.assertIn(Phrase(0, 2, "lung cancer"), phrases)

    def test_text_is_cut_at_max_words(self):
        words, phrases = qt.phrases_of("liver " * (qt.MAX_WORDS + 50))
        self.assertEqual(words, qt.MAX_WORDS)
        self.assertEqual({p.key for p in phrases}, {"liver " * n + "liver" for n in range(qt.MAX_PHRASE_WORDS)} | {"liver"})


class RelatedTest(unittest.TestCase):
    def test_qualifiers_never_match(self):
        self.assertIs(qt.related("type 1 diabetes", "type 2 diabetes"), False)
        self.assertIs(qt.related("t cell", "b cell"), False)
        self.assertIs(qt.related("cd4 t cell", "cd8 t cell"), False)
        self.assertIs(qt.related("stage ii cancer", "stage iii cancer"), False)

    def test_shared_words_and_head_words(self):
        self.assertIs(qt.related("lung tumor", "lung cancer"), True)
        self.assertIs(qt.related("renal", "kidney"), True)
        self.assertIs(qt.related("hepatocellular carcinoma", "liver cancer"), True)
        self.assertIs(qt.related("gut microbiome", "gut microbiota"), True)

    def test_unrelated_words(self):
        self.assertIsNone(qt.related("breast cancer", "mcf 7"))
        self.assertIsNone(qt.related("lung", "tumor"))


class MatchesTest(unittest.TestCase):
    def test_exact_and_alias_without_the_model(self):
        _, phrases = qt.phrases_of("human lung tumours")
        tags = ["Homo sapiens", "lung tumor", "Lung tumours"]
        with mock.patch.object(qt, "vectors_of", side_effect=AssertionError("not needed")):
            # Every phrase that could be embedded is matched exactly or is an alias... except "human lung",
            # so give the model a harmless answer for it.
            pass
        with mock.patch.object(qt, "vectors_of", return_value=np.zeros((0, 768), dtype=np.float32)) as vectors:
            vectors.side_effect = lambda texts: np.zeros((len(texts), 768), dtype=np.float32)
            matches = qt.matches_of(phrases, tags)
        found = {(m.tag, m.phrase.key, m.how) for m in matches}
        self.assertIn(("Homo sapiens", "human", "alias"), found)
        self.assertIn(("lung tumor", "lung tumor", "exact"), found)
        self.assertIn(("Lung tumours", "lung tumor", "exact"), found)

    def test_similar_needs_kinship_or_a_high_cosine(self):
        _, phrases = qt.phrases_of("lung tumours and breast carcinoma")
        tags = ["lung cancer", "MCF-7", "breast cancer"]
        vectors = {
            "lung tumor": [1, 0, 0], "breast carcinoma": [0, 1, 0], "tumors and breast": [0, 0, 1],
            "lung cancer": [0.9, 0.1, 0], "MCF-7": [0, 0.9, 0.1], "breast cancer": [0, 0.8, 0.2],
        }

        def fake(texts):
            out = np.array([vectors.get(t, [0, 0, 0]) for t in texts], dtype=np.float32)
            norms = np.linalg.norm(out, axis=1, keepdims=True)
            return out / np.where(norms == 0, 1, norms)

        with mock.patch.object(qt, "vectors_of", side_effect=fake):
            matches = {(m.tag, m.phrase.key) for m in qt.matches_of(phrases, tags) if m.how == "similar"}
        self.assertIn(("lung cancer", "lung tumor"), matches)  # 0.99, shares "lung"
        self.assertIn(("breast cancer", "breast carcinoma"), matches)  # shares "breast"
        # 0.99 to "breast carcinoma" but no word in common and under SIMILAR_MIN_UNRELATED? No: 0.99 passes it.
        self.assertIn(("MCF-7", "breast carcinoma"), matches)


class ChooseTest(unittest.TestCase):
    CORPUS = {"Homo sapiens": 16382, "lung cancer": 433, "single cell": 425, "lung": 1424, "human lung": 47, "tumor": 704}
    CORPUS_TAGGED = 171671

    def lung_pool(self):
        human = [f"H{i}" for i in range(111)]
        lung_cancer = human[:9] + [f"L{i}" for i in range(13)]
        single_cell = human[9:19] + ["L0"] + [f"S{i}" for i in range(2)]
        return pool(**{
            "Homo sapiens": human, "lung cancer": lung_cancer, "single cell": single_cell,
            "lung": human[:4] + [f"G{i}" for i in range(12)], "human lung": human[:5],
            "tumor": [f"T{i}" for i in range(6)],
        })

    def lung_matches(self):
        # "single-cell RNA-seq of human lung tumours": words 0..7
        return [
            Match("Homo sapiens", Phrase(4, 5, "human"), "alias", 1.0),
            Match("lung cancer", Phrase(5, 7, "lung tumor"), "similar", 0.82),
            Match("single cell", Phrase(0, 2, "single cell"), "exact", 1.0),
            Match("lung", Phrase(5, 6, "lung"), "exact", 1.0),
            Match("human lung", Phrase(4, 6, "human lung"), "exact", 1.0),
            Match("tumor", Phrase(6, 7, "tumor"), "exact", 1.0),
        ]

    def test_the_lung_example(self):
        selected, rows, floor = qt.choose(self.lung_matches(), self.lung_pool(), self.CORPUS, 307, self.CORPUS_TAGGED, [], {})
        self.assertEqual(selected, ["Homo sapiens", "lung cancer"])
        self.assertEqual(floor, 6)
        by_value = {r["value"]: r for r in rows}
        self.assertEqual(by_value["lung cancer"]["remaining"], 9)
        self.assertEqual(by_value["single cell"]["reason"], "too few results would keep every tag")
        self.assertEqual(by_value["lung"]["reason"], "its words already matched a chosen tag")
        self.assertEqual(len(rows), len({r["value"] for r in rows}))  # each tag once
        self.assertTrue(all(r["selected"] for r in rows[:2]))

    def test_the_users_own_tags_are_left_out(self):
        selected, rows, _ = qt.choose(self.lung_matches(), self.lung_pool(), self.CORPUS, 307, self.CORPUS_TAGGED, ["lung cancer"], {})
        self.assertEqual(selected[0], "Homo sapiens")
        self.assertNotIn("lung cancer", selected)
        self.assertNotIn("lung cancer", {r["value"] for r in rows})

    def test_a_longer_exact_match_of_comparable_count_wins(self):
        projects = pool(**{
            "soil": [f"P{i}" for i in range(187)], "soil microbiome": [f"P{i}" for i in range(150)],
            "microbiome": [f"P{i}" for i in range(35)],
        })
        matches = [
            Match("soil", Phrase(0, 1, "soil"), "exact", 1.0),
            Match("soil microbiome", Phrase(0, 2, "soil microbiome"), "exact", 1.0),
            Match("microbiome", Phrase(1, 2, "microbiome"), "exact", 1.0),
        ]
        corpus = {"soil": 2529, "soil microbiome": 1695, "microbiome": 1024}
        selected, rows, _ = qt.choose(matches, projects, corpus, 623, self.CORPUS_TAGGED, [], {})
        self.assertEqual(selected, ["soil microbiome"])
        self.assertEqual({r["value"]: r["reason"] for r in rows if not r["selected"]},
                         {"soil": "its words are part of a longer match", "microbiome": "its words are part of a longer match"})

    def test_a_rare_longer_match_does_not_win(self):
        # "human lung" (5 projects) must not take the words of "human" (111) and "lung".
        selected, _, _ = qt.choose(self.lung_matches(), self.lung_pool(), self.CORPUS, 307, self.CORPUS_TAGGED, [], {})
        self.assertNotIn("human lung", selected)

    def test_spellings_of_a_chosen_tag(self):
        projects = pool(**{"gut microbiota": [f"P{i}" for i in range(119)], "Gut microbiota": [f"Q{i}" for i in range(31)]})
        matches = [
            Match("gut microbiota", Phrase(0, 2, "gut microbiota"), "exact", 1.0),
            Match("Gut microbiota", Phrase(0, 2, "gut microbiota"), "exact", 1.0),
        ]
        selected, rows, _ = qt.choose(matches, projects, {"gut microbiota": 2596, "Gut microbiota": 322}, 406, self.CORPUS_TAGGED, [], {})
        self.assertEqual(selected, ["gut microbiota"])
        self.assertEqual([r["reason"] for r in rows if r["value"] == "Gut microbiota"], ["a spelling of a chosen tag"])

    def test_a_common_name_and_its_species_count_once(self):
        projects = pool(**{"Bombyx mori": [f"P{i}" for i in range(50)], "silkworm": [f"P{i}" for i in range(40)]})
        matches = [
            Match("Bombyx mori", Phrase(0, 2, "bombyx mori"), "exact", 1.0),
            Match("silkworm", Phrase(5, 6, "silkworm"), "exact", 1.0),
        ]
        selected, rows, _ = qt.choose(matches, projects, {"Bombyx mori": 300, "silkworm": 200}, 100, 10000, [], {})
        self.assertEqual(selected, ["Bombyx mori"])
        self.assertEqual([r["reason"] for r in rows if r["value"] == "silkworm"], ["names the same organism as a chosen tag"])
        # The other way round too: the species is skipped after its common name.
        selected, _, _ = qt.choose(matches[::-1], projects, {"Bombyx mori": 200, "silkworm": 300}, 100, 10000, [], {})
        self.assertEqual(len(selected), 1)

    def test_an_abbreviated_binomial_counts_as_its_species(self):
        projects = pool(**{"Schizosaccharomyces pombe": [f"P{i}" for i in range(60)], "S. pombe": [f"P{i}" for i in range(30)]})
        matches = [
            Match("Schizosaccharomyces pombe", Phrase(0, 2, "schizosaccharomyces pombe"), "exact", 1.0),
            Match("S. pombe", Phrase(9, 11, "s pombe"), "exact", 1.0),
        ]
        selected, rows, _ = qt.choose(matches, projects, {}, 100, 10000, [], {})
        self.assertEqual(selected, ["Schizosaccharomyces pombe"])
        self.assertEqual([r["reason"] for r in rows if r["value"] == "S. pombe"], ["names the same organism as a chosen tag"])
        self.assertTrue(qt.same_concept("e coli", "escherichia coli"))
        self.assertFalse(qt.same_concept("s aureus", "staphylococcus epidermidis"))
        self.assertFalse(qt.same_concept("lung cancer", "breast cancer"))

    def test_at_most_max_tags(self):
        projects = {f"tag{i}": {f"P{j}" for j in range(100)} for i in range(qt.MAX_TAGS + 2)}
        matches = [Match(f"tag{i}", Phrase(i, i + 1, f"tag{i}"), "exact", 1.0) for i in range(qt.MAX_TAGS + 2)]
        selected, rows, _ = qt.choose(matches, projects, {}, 100, 1000, [], {})
        self.assertEqual(len(selected), qt.MAX_TAGS)
        self.assertEqual(sum(1 for r in rows if r.get("reason", "").startswith("at most")), 2)


if __name__ == "__main__":
    unittest.main()
