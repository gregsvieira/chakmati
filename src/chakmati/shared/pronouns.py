"""The pronouns the person uses, so the Chakmati talks to (and about) them correctly.

Two places use them. The words the code adds itself (a personality's vocatives: "guri" / "guria" / "amigue") are chosen by pronoun in
shared/personality.py. And the text the model writes is steered with ONE short line added to the system prompt (`prompt_line`), only when
the person said their pronouns: someone who did not say gets nothing extra, no tokens spent and no gender assumed."""

DEFAULT = "none"

# id, how it is shown. "none" = the person preferred not to say: gendered words are avoided, nothing is assumed.
OPTIONS: tuple[tuple[str, str], ...] = (
    ("none", "Prefiro não informar"),
    ("ele", "ele/dele"),
    ("ela", "ela/dela"),
    ("elu", "elu/delu"),
)
_IDS = {pid for pid, _ in OPTIONS}

_LINES = {
    "ele": 'O usuário usa os pronomes ele/dele: ao falar com ele ou sobre ele, use o masculino ("obrigado", "cansado", "bem-vindo").',
    "ela": 'O usuário usa os pronomes ela/dela: ao falar com ela ou sobre ela, use o feminino ("obrigada", "cansada", "bem-vinda").',
    "elu": 'O usuário usa os pronomes elu/delu: ao falar com a pessoa ou sobre ela, evite palavras que marquem gênero; reformule ("que bom te ver" em vez de "bem-vindo").',
}


def valid(pronouns_id: str) -> bool:
    return pronouns_id in _IDS


def normalize(pronouns_id: str | None) -> str:
    """The id when it is a known one, otherwise "none" (an unknown value in the environment never breaks the engine)."""
    return pronouns_id if pronouns_id in _IDS else DEFAULT


def options() -> list[dict[str, str]]:
    return [{"id": pid, "name": name} for pid, name in OPTIONS]


def prompt_line(pronouns_id: str) -> str:
    """The line added to the system prompt, or "" when no pronouns were given."""
    return _LINES.get(pronouns_id, "")
