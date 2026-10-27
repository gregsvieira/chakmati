"""Keeping secrets and personal data out of the agent.

* Paths whose names say "secret" (keys, passwords, wallets, browser profiles, cloud credentials, ...) are never read, listed
  into answers, copied or edited.
* Anything the agent shows (command output, file text) is redacted first: keys, tokens, passwords, private-key blocks, card
  numbers and CPF/CNPJ become [oculto]. The redacted text is all that is kept (the action log stores only that).
This is a safety net over a policy that already refuses these files; no pattern list is perfect, so it is not the only layer."""

import re

SECRET_NAME = re.compile(
    r"(^|[._\-/ ])(env|envrc|netrc|npmrc|pypirc|pgpass|htpasswd|secrets?|credentials?|passwords?|senhas?|passwd|shadow|keychain|wallet|"
    r"id_rsa|id_dsa|id_ecdsa|id_ed25519|private[_\-]?keys?|token|tokens|apikeys?|api[_\-]key|cookies?|login data|"
    r"authorized_keys|known_hosts|kubeconfig|terraform\.tfstate|cpf|rg|passaporte|cnh|cartao|cartão|extrato|imposto|irpf)($|[._\-/ ])"
    r"|\.(pem|key|p12|pfx|keystore|jks|kdbx|gpg|asc|ovpn|cer|crt|der)$"
    r"|(^|/)\.(ssh|aws|gnupg|kube|docker|config|password-store|1password)(/|$)",
    re.IGNORECASE,
)
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)", re.DOTALL)
_ASSIGNMENT = re.compile(r"(?i)\b(password|passwd|senha|secret|token|api[_\-]?key|apikey|authorization|bearer)\b(\s*[:=]\s*|\s+)(?:\"[^\"\n]{3,}\"|'[^'\n]{3,}'|[^\s\"']{6,})")
_PATTERNS = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),  # JWT
    _ASSIGNMENT,
    re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),  # CPF
    re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"),  # CNPJ
]
_CARD = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")
MASK = "[oculto]"


def looks_secret(path_text: str) -> bool:
    return bool(SECRET_NAME.search(path_text.replace("\\", "/")))


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
        alt = not alt
    return total % 10 == 0


def redact(text: str) -> str:
    text = _PRIVATE_KEY.sub(MASK, text)
    for pattern in _PATTERNS:
        if pattern is _ASSIGNMENT:  # keep the name ("password="), hide the value
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)
        else:
            text = pattern.sub(MASK, text)

    def card(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        return MASK if 13 <= len(digits) <= 19 and _luhn(digits) else m.group(0)

    return _CARD.sub(card, text)


def has_secret(text: str) -> bool:
    return redact(text) != text
