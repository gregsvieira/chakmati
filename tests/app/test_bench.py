from chakmati.app.bench import CASES, evaluate
from chakmati.shared.gate.base import GateResult, Route
from chakmati.shared.gate.heuristic import HeuristicGate


class ConstantGate:
    def classify(self, text):
        return GateResult(Route.CHAT, 1.0, "const")


def test_evaluate_reports_accuracy_and_timing():
    stats = evaluate(ConstantGate(), CASES)
    chat_share = sum(1 for _, r in CASES if r is Route.CHAT) / len(CASES)
    assert stats["accuracy"] == chat_share
    assert stats["mean_ms"] >= 0
    assert stats["max_ms"] >= stats["mean_ms"]


def test_cases_cover_all_routes_and_both_languages():
    assert {r for _, r in CASES} == set(Route)
    assert any("pesquise" in t or "crie" in t for t, _ in CASES)


def test_heuristic_gate_is_accurate_on_cases():
    assert evaluate(HeuristicGate(), CASES)["accuracy"] >= 0.85
