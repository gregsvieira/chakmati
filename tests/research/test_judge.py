import json

import httpx

from liteagent.research.evalset import LabelledResult
from liteagent.research.judge import llm_relevance_scorer


def item():
    return LabelledResult("capital da Austrália", 1, "Canberra", "https://x", "É a capital.", 1, "natural")


def test_judge_yes_no_and_prompt():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "Yes"}})

    score = llm_relevance_scorer("http://o.test", "m", transport=httpx.MockTransport(handler))
    assert score(item()) == 1.0
    body = seen[0]
    assert body["think"] is False and body["options"]["temperature"] == 0
    assert body["messages"][1]["content"] == "Query: capital da Austrália\nSearch result: Canberra. É a capital."
    assert "relevant" in body["messages"][0]["content"]


def test_judge_no_and_error():
    no = llm_relevance_scorer("http://o.test", "m", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"message": {"content": "no"}})))
    assert no(item()) == 0.0
    err = llm_relevance_scorer("http://o.test", "m", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert err(item()) == 0.0
