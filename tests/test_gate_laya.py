import importlib.util

import pytest

from chakmati.config import Settings
from chakmati.gate import build_gate, laya_gate
from chakmati.gate.base import Route
from chakmati.gate.heuristic import HeuristicGate
from chakmati.gate.laya_gate import ROUTE_QUESTION, LayaGate


def fake_predictor(choice: str, confidence: float):
    def predict(text, questions):
        assert questions is ROUTE_QUESTION
        return {"answers": {"route": {"choice": choice, "confidence": confidence}}}

    return predict


def test_uses_laya_when_confident():
    gate = LayaGate(HeuristicGate(), 0.6, fake_predictor("research", 0.9))
    result = gate.classify("anything")
    assert result.route is Route.RESEARCH
    assert result.confidence == 0.9
    assert result.source == "laya"


def test_falls_back_on_low_confidence():
    gate = LayaGate(HeuristicGate(), 0.6, fake_predictor("research", 0.3))
    result = gate.classify("olá")
    assert result.source == "heuristic"
    assert result.route is Route.CHAT


def test_falls_back_on_unknown_label():
    gate = LayaGate(HeuristicGate(), 0.6, fake_predictor("banana", 0.99))
    assert gate.classify("olá").source == "heuristic"


def test_falls_back_on_malformed_result():
    gate = LayaGate(HeuristicGate(), 0.6, lambda text, questions: {})
    assert gate.classify("olá").source == "heuristic"


def test_falls_back_when_predictor_raises():
    def boom(text, questions):
        raise RuntimeError("model failed to load")

    gate = LayaGate(HeuristicGate(), 0.6, boom)
    assert gate.classify("olá").source == "heuristic"


def test_falls_back_when_laya_not_installed(monkeypatch):
    def missing():
        raise ImportError("no laya")

    monkeypatch.setattr(laya_gate, "_default_predictor", missing)
    gate = LayaGate(HeuristicGate(), 0.6)
    assert gate.classify("pesquise algo").source == "heuristic"
    # unavailability is remembered; the loader is not retried every call
    assert gate.classify("pesquise algo").route is Route.RESEARCH


@pytest.mark.skipif(
    importlib.util.find_spec("laya") is None, reason="laya not installed"
)
def test_real_laya_model():
    # min_confidence=0 so only an exception can cause a fallback; if this
    # fails with source == "heuristic", see Step 6 (state format).
    gate = LayaGate(HeuristicGate(), min_confidence=0.0)
    result = gate.classify("search the web for the latest Python release")
    assert result.source == "laya"
    assert 0.0 <= result.confidence <= 1.0


def test_build_gate_selects_backend():
    assert isinstance(build_gate(Settings()), HeuristicGate)
    assert isinstance(build_gate(Settings(gate_backend="laya")), LayaGate)
