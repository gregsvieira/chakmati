"""Makes N filled-in copies (PDF) of the three-question maths exam, each with an "X" in the chosen option, to simulate a teacher with a
pile of exams and only the answer key. Prints the real marks (the ground truth) to a JSON file kept OUTSIDE the folder given to the assistant.

    uv run python scripts/simulate_exams.py OUT_DIR TRUTH_JSON [N]
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
.foot{text-align:center;font-weight:bold;position:fixed;bottom:10px;left:0;right:0}"""


def page(name: str, marks: list[list[int]]) -> str:
    qs = ""
    for i, ((text, options), chosen) in enumerate(zip(QUESTIONS, marks)):
        rows = "".join(f'<p class="o"><span class="box">[{"X" if j in chosen else "&nbsp;"}]</span> {LETTERS[j]}) {html.escape(opt)}</p>' for j, opt in enumerate(options))
        qs += f'<div class="q"><b>{i + 1}.</b> {html.escape(text)}{rows}</div>'
    return f"""<html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<div class="head"><div class="date">12 / 11 / 2026</div><p>Escola: <span>Escola Municipal Machado de Assis</span></p><p>Série: <span>9º ano B</span></p>
<p>Professor: <span>Profª Helena Cardoso</span></p><p>Aluno: <span>{html.escape(name)}</span></p></div>
<h1>PROVA DE MATEMÁTICA</h1>{qs}<div class="foot">ATIVIDADESMATEMATICA.COM.BR</div></body></html>"""


def main() -> None:
    out, truth_path = Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser()
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    rng = random.Random(2026)
    out.mkdir(parents=True, exist_ok=True)
    truth = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page_ = browser.new_page()
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
