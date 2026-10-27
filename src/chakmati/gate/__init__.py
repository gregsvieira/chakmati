from chakmati.config import Settings
from chakmati.gate.base import Gate, GateResult, Route
from chakmati.gate.heuristic import HeuristicGate
from chakmati.gate.laya_gate import LayaGate


def build_gate(settings: Settings) -> Gate:
    heuristic = HeuristicGate()
    if settings.gate_backend == "laya":
        return LayaGate(heuristic, settings.gate_min_confidence)
    return heuristic


__all__ = ["Gate", "GateResult", "Route", "HeuristicGate", "LayaGate", "build_gate"]
