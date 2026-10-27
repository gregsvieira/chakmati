"""What a command or an error means, in words a person who never saw a terminal understands.

The checks use the real command (policy.py); this is only how it is SHOWN: "Copiar lista.txt para lista_copia.txt" first, the command itself
after it for whoever wants to see it. Errors from the checks are turned into a sentence that says what to do."""

import os
import re
from pathlib import Path


def _rel(word: str, workspace: str | Path | None) -> str:
    if workspace and os.path.isabs(word):
        try:
            return str(Path(word).relative_to(Path(workspace).resolve()))
        except ValueError:
            return word
    return word


def friendly(argv: list[str], workspace: str | Path | None = None) -> str:
    """"cp a.txt b.txt" -> "Copiar a.txt para b.txt". Unknown commands come back as they are."""
    if not argv:
        return ""
    name, args = argv[0], argv[1:]
    flags = {a for a in args if a.startswith("-") and not re.fullmatch(r"-\d+", a)}
    words = [_rel(a, workspace) for a in args if a not in flags and not re.fullmatch(r"-?\d+", a) and a not in {".", "./"}]
    folder = "a pasta" if "-r" in flags else "o arquivo"
    if name == "mkdir" and words:
        return f"Criar a pasta {words[0]}" if len(words) == 1 else f"Criar as pastas {', '.join(words)}"
    if name == "touch" and words:
        return f"Criar o arquivo {', '.join(words)}"
    if name == "cp" and len(words) == 2:
        return f"Copiar {folder} {words[0]} para {words[1]}"
    if name == "mv" and len(words) == 2:
        same_folder = os.path.dirname(words[0]) == os.path.dirname(words[1])
        return f"{'Renomear' if same_folder else 'Mover'} {words[0]} para {words[1]}"
    if name == "ls":
        return f"Listar os arquivos de {words[0]}" if words else "Listar os arquivos"
    if name in {"cat", "head", "tail"} and words:
        part = {"cat": "o conteúdo", "head": "o começo", "tail": "o fim"}[name]
        return f"Mostrar {part} de {words[0]}"
    if name == "wc" and words:
        return f"Contar linhas e palavras de {words[0]}"
    if name in {"stat", "file"} and words:
        return f"Ver as informações de {words[0]}"
    if name == "du" and words:
        return f"Ver o tamanho de {words[0]}"
    if name == "grep" and len(words) >= 2:
        return f"Procurar “{words[0]}” em {', '.join(words[1:])}"
    if name == "pwd":
        return "Mostrar a pasta atual"
    if name == "date":
        return "Mostrar a data e a hora"
    if name == "df":
        return "Ver o espaço livre em disco"
    if name == "echo":
        return "Mostrar um texto"
    if name in {"curl", "wget"}:
        url = next((a for a in args if a.startswith("https://")), "")
        out = next((_rel(args[i + 1], workspace) for i, a in enumerate(args[:-1]) if a in {"-o", "-O"}), "")
        host = re.sub(r"^https://([^/]+).*$", r"\1", url)
        return f"Baixar de {host}" + (f" e salvar como {out}" if out else "")
    if name in {"python3", "python", "node", "bash", "sh"} and words:
        return f"Rodar o script {words[0]}"
    return " ".join(argv)


_ERRORS = [
    (re.compile(r"\((?:origem|destino)\): não existe|: não existe$"), "Não encontrei esse arquivo ou pasta na pasta de trabalho. Confira o nome."),
    (re.compile(r"só posso (?:escrever em|usar) a pasta de trabalho"), "Só mexo em itens da pasta de trabalho (e leio Documentos, Mesa e Downloads)."),
    (re.compile(r"já existe"), "Já existe um item com esse nome, e eu não sobrescrevo nada. Escolha outro nome."),
    (re.compile(r"não está na lista de comandos permitidos"), "Isso eu ainda não sei fazer por aqui."),
    (re.compile(r"não faço isso \(apagar arquivos\)"), "Eu não apago arquivos, mas posso mandar para a lixeira, de onde dá para recuperar."),
    (re.compile(r"não mudo o formato do arquivo"), "Ao copiar ou renomear, o arquivo precisa manter o mesmo formato (a terminação, como .txt)."),
    (re.compile(r"a pasta de destino não existe"), "A pasta de destino ainda não existe: crie a pasta primeiro."),
    (re.compile(r"não mexo em itens ocultos"), "Eu não mexo em itens ocultos."),
]


def plain_error(message: str) -> str:
    """The sentence for a refusal from the checks; a message that is already a sentence is left as it is."""
    for pattern, sentence in _ERRORS:
        if pattern.search(message):
            return sentence
    return message.rstrip(".") + "."
