"""Questions and summaries about the files the person attached.

Made for modest computers: the model never gets a whole big document. A short file goes in whole; a long one is searched with BM25 (pure
Python, no extra model, no embeddings) and only the few best excerpts (EXCERPT_BUDGET characters) reach the model. A summary of a long file
reads a handful of sections spread over it, one short model call each. The text of a file is data written by someone else: it is fenced and
neutralised like a web page (shared/guard.py), the answer never carries an app marker, and the sources are added by code, not by the model."""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

from chakmati.features.files import chunks
from chakmati.features.files.store import Attachment, AttachmentStore
from chakmati.shared import guard
from chakmati.shared.bm25 import Bm25Scorer
from chakmati.shared.llm import ChatClient
from chakmati.shared.persona import PERSONA

WHOLE_LIMIT = 6000      # a text up to this size goes to the model in full
EXCERPT_BUDGET = 4200   # characters of excerpts for a question about a longer text
MAX_EXCERPTS = 5
SECTIONS = 5            # a long text is summarised from this many sections
SECTION_CHARS = 2400    # how much of each section the model reads
MAX_FILES = 5
MIN_SHARE = 0.6         # a piece must score at least this share of the best one to be sent
EMBED_MAX_PIECES = 150  # embeddings (when the person turned them on) are computed per question: only for a text small enough to be quick

_SUMMARY = re.compile(
    r"\b(resum\w*|sintetiz\w*|sintese|síntese|principais pontos|pontos principais|do que (?:se )?trata|sobre o que (?:é|e|fala|trata)|summar\w*|overview|tl;?dr)\b",
    re.IGNORECASE)

QUESTION_SYSTEM = (
    f"{PERSONA} Você responde perguntas sobre arquivos que a pessoa anexou. Responda SOMENTE com base nos trechos entre <untrusted> e "
    "</untrusted>. Se a resposta não estiver neles, diga que não encontrou no arquivo; não invente. Responda todas as partes da pergunta, de forma direta."
    + guard.UNTRUSTED_RULE)
SUMMARY_SYSTEM = (
    f"{PERSONA} Você resume arquivos que a pessoa anexou. Use SOMENTE o texto entre <untrusted> e </untrusted>, no idioma do pedido. "
    "Um resumo precisa cobrir o texto todo: escreva de 4 a 7 tópicos curtos (um por linha, começando com \"- \"), mesmo que você costume responder em poucas palavras." + guard.UNTRUSTED_RULE)
SECTION_SYSTEM = (
    f"{PERSONA} Resuma em até 3 frases o trecho entre <untrusted> e </untrusted>, no idioma do trecho. Só o que está nele." + guard.UNTRUSTED_RULE)


def wants_summary(question: str) -> bool:
    return bool(_SUMMARY.search(question))


def encode(question: str, ids: list[str]) -> str:
    """What a job keeps: the question and which attachments it is about."""
    return json.dumps({"q": question, "files": list(ids)}, ensure_ascii=False)


def decode(prompt: str) -> tuple[str, list[str]]:
    try:
        data = json.loads(prompt)
        return str(data["q"]), [str(i) for i in data["files"]]
    except (ValueError, KeyError, TypeError):
        return prompt, []


@dataclass(frozen=True)
class Excerpt:
    file: str
    number: int
    text: str


def _fence(text: str) -> str:
    return f"<untrusted>\n{guard.neutralize(text)}\n</untrusted>"


def pick_excerpts(question: str, files: list[Attachment], budget: int = EXCERPT_BUDGET, limit: int = MAX_EXCERPTS, embedder=None) -> list[Excerpt]:
    """The pieces most likely to hold the answer, in the order they appear in the files. A match on nothing falls back to the start of each file.
    Words alone (BM25) cannot match a question in one language with a file in another; `embedder` (optional, anything with `score(question, parts)`) adds the
    meaning, at the cost of one embedding per piece, so it is only used for up to EMBED_MAX_PIECES pieces."""
    pieces = [Excerpt(f.name, n, c) for f in files for n, c in enumerate(chunks.split(f.text), start=1)]
    if not pieces:
        return []
    texts = [p.text for p in pieces]
    scores = Bm25Scorer().score(question, texts)
    if embedder is not None and len(pieces) <= EMBED_MAX_PIECES:
        meaning = embedder.score(question, texts)
        top = max(meaning) or 1.0
        scores = [0.5 * w + 0.5 * (m / top) for w, m in zip(scores, meaning, strict=True)]
    ranked = sorted(range(len(pieces)), key=lambda i: scores[i], reverse=True)
    top = scores[ranked[0]]
    chosen: list[int] = []
    used = 0
    for i in ranked:
        if chosen and scores[i] < MIN_SHARE * top:   # a weak match only takes room that a better piece (or the neighbour of the best one) needs
            break
        if len(chosen) >= limit or (chosen and used + len(pieces[i].text) > budget):
            continue
        chosen.append(i)
        used += len(pieces[i].text)
    if top <= 0:
        chosen = list(range(min(2, len(pieces))))
    else:
        best = ranked[0]   # the answer often continues in the next piece (what happens after the thing that was named)
        after = best + 1
        if after < len(pieces) and after not in chosen and pieces[after].file == pieces[best].file and used + len(pieces[after].text) <= budget:
            chosen.append(after)
    return [pieces[i] for i in sorted(chosen)]


def sources_line(excerpts: list[Excerpt]) -> str:
    by_file: dict[str, list[int]] = {}
    for e in excerpts:
        by_file.setdefault(e.file, []).append(e.number)
    return "Fonte: " + "; ".join(f"{name} (trecho{'s' if len(n) > 1 else ''} {', '.join(map(str, n))})" for name, n in by_file.items())


def sections(text: str, count: int = SECTIONS, size: int = SECTION_CHARS) -> list[str]:
    """`count` stretches spread over the text, each cut at `size`: a long file is sampled, not read to the end."""
    if len(text) <= count * size:
        return [text[i:i + size] for i in range(0, len(text), size)]
    step = len(text) // count
    return [text[i * step:i * step + size] for i in range(count)]


class FileAssistant:
    def __init__(self, llm: ChatClient, store: AttachmentStore, embedder=None):
        self._llm = llm
        self._store = store
        self._embedder = embedder  # None = words only (the default: nothing extra to run on a modest computer)

    async def _say(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        if hasattr(self._llm, "stream_chat"):
            async for delta in self._llm.stream_chat(messages):  # type: ignore[attr-defined]
                yield delta
        else:
            yield await self._llm.chat(messages)

    def _load(self, ids: list[str]) -> tuple[list[Attachment], list[str]]:
        found, missing = [], []
        for attachment_id in ids[:MAX_FILES]:
            attachment = self._store.get(attachment_id)
            (found if attachment else missing).append(attachment or attachment_id)
        return found, missing  # type: ignore[return-value]

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        question, ids = decode(prompt)
        files, missing = self._load(ids)
        if not files:
            yield "Não achei o arquivo anexado (ele pode ter sido apagado). Anexe de novo com o botão +."
            return
        if missing:
            yield "Um dos arquivos não está mais disponível; respondo com os outros.\n\n"
        if wants_summary(question):
            async for piece in self._summary(question, files):
                yield piece
        else:
            async for piece in self._question(question, files):
                yield piece

    async def _question(self, question: str, files: list[Attachment]) -> AsyncIterator[str]:
        total = sum(f.chars for f in files)
        if total <= WHOLE_LIMIT:
            excerpts = [Excerpt(f.name, 1, f.text) for f in files]
            shown = "\n\n".join(f"[{f.name}]\n{f.text}" for f in files)
            sources = ""
        else:
            excerpts = await asyncio.to_thread(pick_excerpts, question, files, embedder=self._embedder)
            shown = "\n\n".join(f"[{e.file}, trecho {e.number}]\n{e.text}" for e in excerpts)
            sources = sources_line(excerpts)
        messages = [{"role": "system", "content": QUESTION_SYSTEM},
                    {"role": "user", "content": f"{_fence(shown)}\n\nPergunta: {question}"}]
        async for delta in self._say(messages):
            yield guard.strip_markers(delta)
        if sources:
            yield f"\n\n{sources}"

    async def _summary(self, question: str, files: list[Attachment]) -> AsyncIterator[str]:
        parts: list[str] = []
        sampled = False
        for f in files[:3]:
            if f.chars <= WHOLE_LIMIT:
                parts.append(f"[{f.name}]\n{f.text}")
                continue
            sampled = True
            blocks = sections(f.text)
            yield f"Arquivo longo ({f.name}): resumindo {len(blocks)} partes, isso leva um pouco.\n\n"
            notes = []
            for block in blocks:
                notes.append("".join([d async for d in self._say([
                    {"role": "system", "content": SECTION_SYSTEM}, {"role": "user", "content": _fence(block)}])]).strip())
            parts.append(f"[{f.name}: resumos de partes do arquivo]\n" + "\n".join(f"- {n}" for n in notes if n))
        messages = [{"role": "system", "content": SUMMARY_SYSTEM},
                    {"role": "user", "content": f"{_fence(chr(10).join(parts))}\n\nPedido: {question}"}]
        async for delta in self._say(messages):
            yield guard.strip_markers(delta)
        if sampled:
            yield "\n\n(Resumo feito a partir de trechos espalhados pelo arquivo, que é longo: pergunte sobre um assunto para eu buscar o ponto exato.)"

    async def answer(self, prompt: str) -> str:
        return "".join([piece async for piece in self.stream(prompt)]).strip()
