import importlib.util
import time

from .gate.base import Gate, Route
from .gate.heuristic import HeuristicGate
from .gate.laya_gate import LayaGate

CASES: list[tuple[str, Route]] = [
    ("olá", Route.CHAT),
    ("oi, tudo bem?", Route.CHAT),
    ("what is the capital of France?", Route.CHAT),
    ("me explica o que é uma API", Route.CHAT),
    ("tell me a joke", Route.CHAT),
    ("search the web for the latest Python release", Route.RESEARCH),
    ("pesquise as notícias de hoje sobre IA", Route.RESEARCH),
    ("busque o preço atual do dólar", Route.RESEARCH),
    ("find out who won the game last night", Route.RESEARCH),
    ("what's the latest iPhone?", Route.RESEARCH),
    ("write a python script that renames files", Route.TASK),
    ("crie um script que organize meus arquivos", Route.TASK),
    ("refactor this function to be async", Route.TASK),
    ("rode os testes do projeto", Route.TASK),
    ("o que tenho na agenda amanhã?", Route.CALENDAR),
    ("marque uma reunião sexta às 15h", Route.CALENDAR),
]


def evaluate(gate: Gate, cases: list[tuple[str, Route]]) -> dict[str, float]:
    correct = 0
    times: list[float] = []
    for text, expected in cases:
        start = time.perf_counter()
        result = gate.classify(text)
        times.append(time.perf_counter() - start)
        correct += result.route is expected
    return {
        "accuracy": correct / len(cases),
        "mean_ms": 1000 * sum(times) / len(times),
        "max_ms": 1000 * max(times),
    }


def main() -> None:
    gates: dict[str, Gate] = {"heuristic": HeuristicGate()}
    if importlib.util.find_spec("laya") is not None:
        laya = LayaGate(HeuristicGate(), min_confidence=0.0)
        laya.classify("warm up")  # exclude model load from timings
        gates["laya"] = laya
    for name, gate in gates.items():
        s = evaluate(gate, CASES)
        print(
            f"{name:10s} accuracy={s['accuracy']:.2f} "
            f"mean={s['mean_ms']:.1f}ms max={s['max_ms']:.1f}ms"
        )


if __name__ == "__main__":
    main()
