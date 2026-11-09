"""Cut a text into pieces of about `size` characters, at paragraph or sentence edges, so a piece reads on its own."""

import re

_SENTENCE = re.compile(r"(?<=[.!?…])\s+")


def split(text: str, size: int = 900) -> list[str]:
    pieces: list[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n|\n(?=\[(?:página|slide|planilha))", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        units = [paragraph] if len(paragraph) <= size else [u for u in _SENTENCE.split(paragraph) if u]
        for unit in units:
            while len(unit) > size:  # a run of text with no stop at all (a table row, a code line): cut it hard
                if current:
                    pieces.append(current)
                    current = ""
                pieces.append(unit[:size])
                unit = unit[size:]
            if current and len(current) + len(unit) + 1 > size:
                pieces.append(current)
                current = unit
            else:
                current = f"{current}\n{unit}" if current else unit
    if current:
        pieces.append(current)
    return pieces
