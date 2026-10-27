"""Makes N filled-in copies (PDF) of the three-question maths exam, each with an "X" in the chosen option, to simulate a teacher with a
pile of exams and only the answer key. Prints the real marks (the ground truth) to a JSON file kept OUTSIDE the folder given to the assistant.

    uv run python scripts/simulate_exams.py OUT_DIR TRUTH_JSON [N] [--scan]

--scan: instead of text PDFs, makes what a scanner or a phone camera would: the name and the X in handwriting-like type, a slight tilt, blur and
noise, saved as image-only PDFs (and a few JPG photos). The real marks are the same ground truth.
"""

import html
import json
import random
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

QUESTIONS = [
    ("(ENEM 2024) Um pintor pretende fazer uma reprodução do quadro Guernica em uma tela de dimensões 20 cm por 30 cm. Essa obra, de autoria do espanhol Pablo Picasso, é uma pintura com 3,6 m de altura e 7,8 m de comprimento. A reprodução a ser feita deverá preencher a maior área possível da tela, mantendo a proporção entre as dimensões da obra original. A escala que deve ser empregada para essa reprodução é:",
     ["1 : 12.", "1 : 18.", "1 : 21.", "1 : 23.", "1 : 26."]),
    ("(ENEM 2024) Na planta baixa de uma casa, um quarto retangular, cuja área é de 24 m², está representado por um retângulo com lados medindo 0,10 m e 0,15 m. A escala dessa planta é:",
     ["1 : 24.", "1 : 40.", "1 : 60.", "1 : 1600.", "1 : 16000."]),
    ("(Enem 2019) Para contratar três máquinas que farão o reparo de vias rurais de um município, a prefeitura elaborou um edital que, entre outras cláusulas, previa: cada empresa interessada só pode cadastrar uma única máquina para concorrer ao edital; o total de recursos destinados para contratar o conjunto das três máquinas é de R$ 31.000,00; o valor a ser pago a cada empresa será inversamente proporcional à idade de uso da máquina cadastrada pela empresa para o presente edital. As três empresas vencedoras do edital cadastraram máquinas com 2, 3 e 5 anos de idade de uso. Quanto receberá a empresa que cadastrou a máquina com maior idade de uso?",
     ["R$ 3.100,00", "R$ 6.000,00", "R$ 6.200,00", "R$ 15.000,00", "R$ 15.500,00"]),
]
KEY = "EBB"  # 1E - 2B - 3B (the answer key is NOT printed on the students' copies)
LETTERS = "ABCDE"
NAMES = ["Ana Beatriz Souza", "Bruno Henrique Lima", "Carla Mendes Ribeiro", "Daniel Alves Pereira", "Eduarda Martins Costa", "Felipe Rocha Barbosa",
         "Gabriela Nunes Teixeira", "Heitor Carvalho Dias", "Isabela Freitas Moura", "João Pedro Cardoso", "Karina Azevedo Lopes", "Lucas Gabriel Ramos",
         "Mariana Oliveira Pinto", "Nicolas Batista Araújo", "Olívia Castro Monteiro", "Pedro Augusto Farias", "Quésia Duarte Machado", "Rafael Santana Gomes",
         "Sofia Vasconcelos Reis", "Thiago Moreira Cunha"]

CSS = """body{font-family:Helvetica,Arial,sans-serif;font-size:13.5px;margin:0;line-height:1.4}
.head{border:2px solid #000;border-radius:28px;padding:16px 36px;margin-bottom:14px;position:relative}
.head p{margin:7px 0;font-weight:bold}.head span{display:inline-block;border-bottom:1.5px solid #000;min-width:300px;font-weight:normal;padding:0 6px}
.date{position:absolute;right:20px;top:12px;border:2px solid #000;border-radius:20px;padding:6px 26px;font-weight:bold}
h1{text-align:center;font-size:24px;margin:6px 0 10px}.q{margin-bottom:16px;text-align:justify}
.o{margin:0}.box{display:inline-block;width:20px;text-align:center;font-weight:bold}
.hand .box{font-family:"Bradley Hand","Noteworthy","Chalkboard SE",cursive;font-size:19px;color:#1a2a6c}.hand .head span{font-family:"Bradley Hand","Noteworthy",cursive;font-size:18px;color:#1a2a6c}
.hand{padding:26px 40px}.foot{text-align:center;font-weight:bold;position:fixed;bottom:10px;left:0;right:0}"""


def page(name: str, marks: list[list[int]], hand: bool = False) -> str:
    qs = ""
    for i, ((text, options), chosen) in enumerate(zip(QUESTIONS, marks)):
        rows = "".join(f'<p class="o"><span class="box">[{"X" if j in chosen else "&nbsp;"}]</span> {LETTERS[j]}) {html.escape(opt)}</p>' for j, opt in enumerate(options))
        qs += f'<div class="q"><b>{i + 1}.</b> {html.escape(text)}{rows}</div>'
    return f"""<html><head><meta charset="utf-8"><style>{CSS}</style></head><body class="{"hand" if hand else ""}">
<div class="head"><div class="date">12 / 11 / 2026</div><p>Escola: <span>Escola Municipal Machado de Assis</span></p><p>Série: <span>9º ano B</span></p>
<p>Professor: <span>Profª Helena Cardoso</span></p><p>Aluno: <span>{html.escape(name)}</span></p></div>
<h1>PROVA DE MATEMÁTICA</h1>{qs}<div class="foot">ATIVIDADESMATEMATICA.COM.BR</div></body></html>"""


def degrade(png_path: Path, rng: random.Random):
    """A page as a scanner or a phone sees it: grey paper, a little tilt, blur, noise."""
    from PIL import Image, ImageEnhance, ImageFilter
    img = Image.open(png_path).convert("L")
    img = img.rotate(rng.uniform(-1.2, 1.2), resample=Image.BICUBIC, fillcolor=235, expand=False)
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.5, 1.0)))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.75, 0.9))
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.93, 1.0))
    noise = Image.effect_noise(img.size, rng.uniform(10, 18))
    return Image.blend(img, noise, 0.07)


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--scan"]
    scan = "--scan" in sys.argv
    out, truth_path = Path(args[0]).expanduser(), Path(args[1]).expanduser()
    n = int(args[2]) if len(args) > 2 else 20
    rng = random.Random(2026)
    out.mkdir(parents=True, exist_ok=True)
    truth = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page_ = browser.new_page(viewport={"width": 794, "height": 1123}, device_scale_factor=2)
        for i, name in enumerate(NAMES[:n], 1):
            marks = []
            for q, right in enumerate(KEY):
                r = rng.random()
                if r < 0.45:
                    marks.append([LETTERS.index(right)])          # right
                elif r < 0.88:
                    marks.append([rng.choice([j for j in range(5) if LETTERS[j] != right])])  # wrong
                elif r < 0.94:
                    marks.append([])                              # left blank
                else:
                    marks.append(sorted(rng.sample(range(5), 2)))  # two marked: counts as wrong
            if scan:
                as_photo = i % 4 == 0  # one in four is a phone photo (JPG), the rest are scanned PDFs
                file = f"prova_{i:02d}.{'jpg' if as_photo else 'pdf'}"
                page_.set_content(page(name, marks, hand=True))
                png = out / f".tmp{i}.png"
                page_.screenshot(path=str(png), full_page=False)
                img = degrade(png, rng)
                png.unlink()
                img.save(out / file, quality=82) if as_photo else img.save(out / file, "PDF", resolution=150)
            else:
                file = f"prova_{i:02d}.pdf"
                page_.set_content(page(name, marks))
                page_.pdf(path=str(out / file), format="A4", margin={"top": "14mm", "bottom": "14mm", "left": "14mm", "right": "14mm"})
            truth[file] = {"aluno": name, "marcado": ["".join(LETTERS[j] for j in m) or "-" for m in marks]}
            truth[file]["acertos"] = sum(1 for m, k in zip(marks, KEY) if m == [LETTERS.index(k)])
        browser.close()
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    truth_path.write_text(json.dumps({"gabarito": "1E 2B 3B", "provas": truth}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(truth)} provas em {out}; verdade em {truth_path}")


if __name__ == "__main__":
    main()
