from .evalset import ITEMS, pairwise_accuracy, strategy_report
from .prune import PruneConfig, prune, prune_by_rank, prune_relative_to_best
from .scorer import LayaPartScorer


def main() -> None:
    scorer = LayaPartScorer()
    scores: list[float] = []
    for item in ITEMS:
        (score,) = scorer.score(item.question, [item.part])
        scores.append(score)
        print(f"{item.kind:10s} {score:.3f}  {item.part}")
    print()
    for kind, acc in pairwise_accuracy(ITEMS, scores).items():
        print(f"good > {kind:10s} pairwise accuracy = {acc:.2f}")
    strategies = {
        "threshold>=0.5": lambda p, sc: prune(p, sc, PruneConfig(0.5, max_keep=99)),
        "rank top 50%": lambda p, sc: prune_by_rank(p, sc, 0.5),
        "rank top 75%": lambda p, sc: prune_by_rank(p, sc, 0.75),
        "within 50% of best": lambda p, sc: prune_relative_to_best(p, sc, 0.5),
        "within 25% of best": lambda p, sc: prune_relative_to_best(p, sc, 0.25),
    }
    print()
    print(f"{'strategy':20s} good_kept irrelevant_dropped wrong_dropped")
    for name, r in strategy_report(ITEMS, scores, strategies).items():
        print(
            f"{name:20s} {r['good_kept']:9.2f} {r['irrelevant_dropped']:17.2f} "
            f"{r['wrong_dropped']:13.2f}"
        )
    if all(s == 1.0 for s in scores):
        print("WARNING: every score is 1.0 - Laya is probably not installed (fail-safe).")


if __name__ == "__main__":
    main()
