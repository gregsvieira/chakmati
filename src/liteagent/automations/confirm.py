"""Is this short message a yes or a no to "Confirma?" Only whole, short replies count ("sim", "pode criar", "não, cancela"):
a sentence that merely contains the word "sim" is something else."""

import re
import unicodedata

_YES = {"sim", "confirmo", "confirmado", "confirma", "pode", "pode criar", "pode sim", "isso", "isso mesmo", "claro", "ok", "okay", "certo", "cria", "crie", "faz", "faca", "manda ver", "com certeza", "positivo", "beleza", "bora", "pode ser", "aprovado", "aprovo"}
_NO = {"nao", "nao quero", "cancela", "cancele", "cancelar", "deixa", "deixa pra la", "esquece", "nao crie", "nao cria", "nao precisa", "para", "pare", "negativo", "recuso", "recusado", "melhor nao", "nao confirmo"}


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", "".join(c for c in decomposed if not unicodedata.combining(c)))).strip()


def verdict(text: str) -> str | None:
    """'yes', 'no' or None."""
    t = _plain(text)
    if not t or len(t.split()) > 4:
        return None
    if t in _NO or t.split()[0] == "nao":
        return "no"
    if t in _YES:
        return "yes"
    return None
