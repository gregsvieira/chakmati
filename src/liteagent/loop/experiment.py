from .evalset import ITEMS, pairwise_accuracy
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
    if all(s == 1.0 for s in scores):
        print("WARNING: every score is 1.0 - Laya is probably not installed (fail-safe).")


if __name__ == "__main__":
    main()
