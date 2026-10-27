from collections.abc import Callable

import httpx

from chakmati.research.evalset import LabelledResult

SYSTEM = (
    "Decide if the search result is relevant to the query, meaning the page would help "
    "answer it. Reply with exactly one word: yes or no."
)


def llm_relevance_scorer(
    base_url: str,
    model: str,
    transport: httpx.BaseTransport | None = None,
) -> Callable[[LabelledResult], float]:
    http = httpx.Client(base_url=base_url, transport=transport, timeout=300.0)

    def score(item: LabelledResult) -> float:
        try:
            response = http.post(
                "/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0, "num_predict": 8},
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": f"Query: {item.query}\nSearch result: {item.text}"},
                    ],
                },
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return 0.0
        reply = response.json()["message"]["content"].strip().lower()
        return 1.0 if reply.startswith(("yes", "sim")) else 0.0

    return score
