from chakmati.research.filter import filter_results, rank_passages
from chakmati.research.search import SearchResult


class WordScorer:
    """score = 0.9 if 'bom' in text, 0.5 if 'meio' in text, else 0.05"""

    def score(self, question, parts):
        return [0.9 if "bom" in p else 0.5 if "meio" in p else 0.05 for p in parts]


def r(n, snippet):
    return SearchResult(f"t{n}", f"https://x/{n}", snippet)


def test_filter_keeps_relevant_in_original_order():
    results = [r(1, "bom"), r(2, "lixo"), r(3, "bom"), r(4, "lixo"), r(5, "bom")]
    kept = filter_results("q", results, WordScorer(), cutoff=0.2, min_keep=2)
    assert [x.url for x in kept] == ["https://x/1", "https://x/3", "https://x/5"]


def test_filter_min_keep_floor_takes_best_when_too_few_pass():
    results = [r(1, "lixo"), r(2, "meio"), r(3, "lixo"), r(4, "bom")]
    kept = filter_results("q", results, WordScorer(), cutoff=0.8, min_keep=2)
    assert [x.url for x in kept] == ["https://x/2", "https://x/4"]


def test_filter_empty():
    assert filter_results("q", [], WordScorer()) == []


def test_rank_passages_top_k_in_input_order():
    passages = ["lixo a", "bom 1", "meio", "bom 2", "lixo b"]
    assert rank_passages("q", passages, WordScorer(), top_k=3) == ["bom 1", "meio", "bom 2"]


def test_rank_passages_fewer_than_k_and_empty():
    assert rank_passages("q", ["bom"], WordScorer(), top_k=4) == ["bom"]
    assert rank_passages("q", [], WordScorer()) == []
