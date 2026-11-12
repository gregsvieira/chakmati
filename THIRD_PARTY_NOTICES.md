# Third-party notices

Chakmati itself is licensed under the Apache License 2.0 (see `LICENSE` and `NOTICE`). It uses, installs or talks to the software below, each under its own
license. This file says what is **shipped in the installers**, what is **installed on the person's computer** on first run (from the official sources, not
shipped by Chakmati), and what Chakmati only **talks to**. Versions are the ones pinned in `uv.lock` when this file was written.

## 1. Shipped inside the installers

| Component | License | Notes |
|---|---|---|
| Electron (and the Chromium it embeds) | MIT; Chromium and its dependencies under their own licenses | The full texts are inside the app: `LICENSE` and `LICENSES.chromium.html` (added by electron-builder). https://www.electronjs.org |
| uv 0.11.15 (a pinned copy, checked by SHA-256) | Apache-2.0 **or** MIT | Used to create the engine's Python environment. https://github.com/astral-sh/uv (`LICENSE-APACHE`, `LICENSE-MIT`). The Apache-2.0 text is the `LICENSE` file shipped with the installer. |
| Chakmati's own code | Apache-2.0 | `LICENSE`, `NOTICE`, this file and `DISCLAIMER.md` are copied into the installers (`legal/` folder of the app's resources). |

## 2. Piper (voice): GPL-3.0-or-later, run as a separate program

The enhanced voice uses **Piper** (`piper-tts`, https://github.com/OHF-Voice/piper1-gpl), which is **GPL-3.0-or-later**. To keep that license separate from
Chakmati's:

- Piper is an **optional extra** (`uv sync --extra voice`). It is **not shipped** in the installers: it is installed on the person's computer, on request, from PyPI.
- The engine **never imports** Piper. It starts it as its own program (`python -m piper`), sends the text on its standard input and reads back a WAV file
  (`src/chakmati/shared/voice/tts.py`, function `_run_piper`). The two programs only talk through those pipes, as separate programs do.
- The source of Piper is available at the address above, as the GPL requires of whoever distributes it. If you redistribute Piper yourself, the GPL applies to you.
- The voice **"jeff"** (pt_BR, medium) is downloaded from https://huggingface.co/rhasspy/piper-voices; its dataset is **CC0** (public domain dedication).

## 3. Libraries with copyleft or special terms (installed on first run)

| Package | License | Why it is fine here |
|---|---|---|
| recurring-ical-events, x-wr-timezone | LGPL-3.0-or-later | Used as ordinary libraries, unmodified, installed from PyPI by the person's own computer: the person can replace them. |
| tld | MPL-1.1 **or** GPL-2.0-only **or** LGPL-2.1-or-later | Chakmati takes it under the **MPL-1.1** option (file-level copyleft; unmodified). |
| certifi, tqdm | MPL-2.0 (tqdm: MPL-2.0 AND MIT) | File-level copyleft; unmodified. |
| NVIDIA CUDA libraries (`nvidia-*`, `cuda-toolkit`) | NVIDIA proprietary license | Only come with the optional **Laya** extra (PyTorch) on Linux. Not shipped by Chakmati: PyPI delivers them to the person's computer, under NVIDIA's terms (https://docs.nvidia.com/cuda/eula/). |

## 4. Models and voices (downloaded to the person's computer, never shipped)

| Model | Use | License (check the model card before redistributing) |
|---|---|---|
| Qwen3.5 (Alibaba) | chat | see the model card on https://ollama.com/library |
| Granite 4 (IBM) | chat | Apache-2.0 |
| deepseek-r1 | explaining exams (optional) | MIT |
| nomic-embed-text | embeddings (optional) | Apache-2.0 |
| Whisper "base" via faster-whisper | speech to text | MIT |
| Piper voice "jeff" (pt_BR) | text to speech | CC0 (dataset) |
| Laya (Convai Innovations) | optional, not recommended | Apache-2.0 |

## 5. Programs Chakmati talks to but does not ship

| Program | License / terms | Notes |
|---|---|---|
| Ollama | MIT | The local model server. https://ollama.com |
| OpenWA (`@open-wa/wa-automate`) | Hippocratic + Do No Harm 1.1 | Installed by the person with `scripts/openwa.sh`, not shipped. It automates WhatsApp Web, which WhatsApp's terms do not allow (see `DISCLAIMER.md`). |
| Home Assistant | Apache-2.0 | Run in a container image the person pulls. |
| Docker Desktop | Docker subscription terms | Downloaded from docker.com on the person's request (paid for larger companies). |
| Google Chrome | Google's terms | Driven through Playwright (Apache-2.0, below). |
| SearXNG, DuckDuckGo | AGPL-3.0 (SearXNG, a server the person runs); the DuckDuckGo service has its own terms | Only queried over HTTP. |

## 6. Python packages used by the engine

Installed from PyPI by `uv` on the person's computer (none is shipped in the installers). Core packages and the optional extras are listed together;
each package's own license file is in its distribution.

| Package | Version | License | Home |
|---|---|---|---|
| annotated-doc | 0.0.5 | MIT | https://github.com/fastapi/annotated-doc |
| annotated-types | 0.8.0 | MIT | https://github.com/annotated-types/annotated-types |
| anyio | 4.15.1 | MIT | https://github.com/agronholm/anyio |
| av | 16.1.0 | BSD-3-Clause | https://github.com/PyAV-Org/PyAV |
| babel | 2.18.0 | BSD License | https://babel.pocoo.org/ |
| certifi | 2026.10.23 | Mozilla Public License 2.0 (MPL 2.0) | https://github.com/certifi/python-certifi |
| cffi | 2.1.1 | MIT-0 | https://github.com/python-cffi/cffi |
| charset-normalizer | 3.5.2 | MIT | https://pypi.org/project/charset-normalizer/ |
| click | 8.5.0 | BSD-3-Clause | https://github.com/pallets/click/ |
| colorama | 0.4.6 | BSD License | https://github.com/tartley/colorama |
| courlan | 1.4.0 | Apache-2.0 | https://github.com/adbar/courlan |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| ctranslate2 | 4.8.3 | MIT | https://opennmt.net |
| cuda-bindings | 13.4.4 | Apache-2.0 | https://github.com/NVIDIA/cuda-python |
| cuda-pathfinder | 1.8.4 | Apache-2.0 | https://github.com/NVIDIA/cuda-python |
| cuda-toolkit | 13.0.3.0 | ? | https://developer.nvidia.com/cuda-toolkit |
| dateparser | 1.4.3 | BSD-3-Clause | https://github.com/scrapinghub/dateparser |
| et-xmlfile | 2.0.0 | MIT License | https://foss.heptapod.net/openpyxl/et_xmlfile |
| fastapi | 0.161.1 | MIT | https://github.com/fastapi/fastapi |
| faster-whisper | 1.2.1 | MIT License | https://github.com/SYSTRAN/faster-whisper |
| filelock | 4.2.4 | MIT | https://github.com/tox-dev/py-filelock |
| flatbuffers | 25.12.19 | Apache Software License | https://google.github.io/flatbuffers/ |
| fsspec | 2026.9.0 | BSD-3-Clause | https://github.com/fsspec/filesystem_spec |
| greenlet | 3.5.6 | MIT AND PSF-2.0 | https://greenlet.readthedocs.io |
| h11 | 0.16.0 | MIT License | https://github.com/python-hyper/h11 |
| hf-xet | 1.7.0 | Apache-2.0 | https://github.com/huggingface/xet-core |
| htmldate | 1.11.0 | Apache-2.0 | https://htmldate.readthedocs.io |
| httpcore | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ |
| httpcore2 | 2.16.0 | BSD-3-Clause | https://github.com/pydantic/httpx2 |
| httpx | 0.28.1 | BSD License | https://github.com/encode/httpx |
| httpx2 | 2.16.0 | BSD-3-Clause | https://github.com/pydantic/httpx2 |
| httpx2-jsfetch | 1.0 | BSD-3-Clause | https://pypi.org/project/httpx2-jsfetch/ |
| huggingface-hub | 2.3.0 | Apache Software License | https://github.com/huggingface/huggingface_hub |
| icalendar | 7.3.0 | BSD-2-Clause | https://icalendar.readthedocs.io/en/stable/ |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna |
| jinja2 | 3.1.6 | BSD License | https://github.com/pallets/jinja/ |
| justext | 3.0.2 | BSD License | https://github.com/miso-belica/jusText |
| laya | 0.4.14 | Apache Software License | https://huggingface.co/convaiinnovations/laya |
| lxml | 6.1.3 | BSD-3-Clause | https://lxml.de/ |
| lxml-html-clean | 0.4.5 | BSD-3-Clause | https://github.com/fedora-python/lxml_html_clean/ |
| markdown-it-py | 4.2.0 | MIT License | https://github.com/executablebooks/markdown-it-py |
| markupsafe | 3.0.4 | BSD-3-Clause | https://github.com/pallets/markupsafe/ |
| mdurl | 0.1.2 | MIT License | https://github.com/executablebooks/mdurl |
| mpmath | 1.3.0 | BSD License | http://mpmath.org/ |
| networkx | 3.6.1 | BSD-3-Clause | https://networkx.org/ |
| networkx | 3.7 | BSD-3-Clause | https://networkx.org/ |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| nvidia-cublas | 13.1.1.3 | LicenseRef-NVIDIA-Proprietary | https://developer.nvidia.com/cuda-zone |
| nvidia-cuda-cupti | 13.0.85 | Other/Proprietary License | https://developer.nvidia.com/cuda-zone |
| nvidia-cuda-nvrtc | 13.0.88 | Other/Proprietary License | https://developer.nvidia.com/cuda-zone |
| nvidia-cuda-runtime | 13.0.96 | ? | https://developer.nvidia.com/cuda-zone |
| nvidia-cudnn-cu13 | 9.24.0.43 | ? | https://developer.nvidia.com/cuda-zone |
| nvidia-cufft | 12.0.0.61 | Other/Proprietary License | https://developer.nvidia.com/cuda-zone |
| nvidia-cufile | 1.15.1.6 | Other/Proprietary License | https://developer.nvidia.com/cuda-zone |
| nvidia-curand | 10.4.0.35 | Other/Proprietary License | https://developer.nvidia.com/cuda-zone |
| nvidia-cusolver | 12.0.4.66 | Other/Proprietary License | https://developer.nvidia.com/cuda-zone |
| nvidia-cusparse | 12.6.3.3 | Other/Proprietary License | https://developer.nvidia.com/cuda-zone |
| nvidia-cusparselt-cu13 | 0.8.1 | NVIDIA Proprietary Software | https://developer.nvidia.com/cusparselt |
| nvidia-nccl-cu13 | 2.30.7 | ? | https://developer.nvidia.com/cuda-zone |
| nvidia-nvjitlink | 13.4.92 | LicenseRef-NVIDIA-Proprietary | https://developer.nvidia.com/cuda-zone |
| nvidia-nvshmem-cu13 | 3.4.5 | ? | https://developer.nvidia.com/cuda-zone |
| nvidia-nvtx | 13.0.85 | Other/Proprietary License | https://developer.nvidia.com/cuda-zone |
| onnxruntime | 1.31.0 | MIT License | https://onnxruntime.ai |
| opencv-python | 5.0.0.93 | Apache Software License | https://github.com/opencv/opencv-python |
| openpyxl | 3.1.5 | MIT License | https://openpyxl.readthedocs.io |
| opentelemetry-api | 1.45.1 | Apache-2.0 | https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-api |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| pathvalidate | 3.3.1 | MIT License | https://github.com/thombashi/pathvalidate |
| pillow | 13.0.0 | MIT-CMU | https://python-pillow.org |
| piper-tts | 1.8.0 | GPL-3.0-or-later | http://github.com/OHF-voice/piper1-gpl |
| playwright | 1.64.1 | Apache-2.0 | https://github.com/Microsoft/playwright-python |
| protobuf | 7.36.2 | 3-Clause BSD License | https://developers.google.com/protocol-buffers/ |
| pyclipper | 1.4.0 | MIT License | https://github.com/fonttools/pyclipper |
| pycparser | 3.12 | BSD-3-Clause | https://github.com/eliben/pycparser |
| pydantic | 2.14.1 | MIT | https://github.com/pydantic/pydantic |
| pydantic-core | 2.50.1 | MIT | https://github.com/pydantic/pydantic |
| pyee | 13.0.1 | MIT License | https://github.com/jfhbrook/pyee |
| pyee | 14.0.0 | MIT License | https://github.com/jfhbrook/pyee |
| pygments | 2.21.0 | BSD-2-Clause | https://pygments.org |
| pyobjc-core | 12.2.2 | MIT | https://github.com/ronaldoussoren/pyobjc |
| pyobjc-framework-cocoa | 12.2.2 | MIT | https://github.com/ronaldoussoren/pyobjc |
| pyobjc-framework-coreml | 12.2.2 | MIT | https://github.com/ronaldoussoren/pyobjc |
| pyobjc-framework-eventkit | 12.2.2 | MIT | https://github.com/ronaldoussoren/pyobjc |
| pyobjc-framework-quartz | 12.2.2 | MIT | https://github.com/ronaldoussoren/pyobjc |
| pyobjc-framework-vision | 12.2.2 | MIT | https://github.com/ronaldoussoren/pyobjc |
| pypdf | 6.21.2 | BSD-3-Clause | https://github.com/py-pdf/pypdf |
| pypdfium2 | 5.14.0 | BSD-3-Clause, Apache-2.0, dependency licenses | https://github.com/pypdfium2-team/pypdfium2 |
| python-dateutil | 2.9.0.post0 | BSD License / Apache Software License | https://github.com/dateutil/dateutil |
| python-docx | 1.2.0 | MIT License | https://github.com/python-openxml/python-docx |
| python-pptx | 1.0.2 | MIT License | https://github.com/scanny/python-pptx |
| pytz | 2026.5 | MIT License | http://pythonhosted.org/pytz |
| pyyaml | 6.0.3 | MIT License | https://pyyaml.org/ |
| rapidocr-onnxruntime | 1.4.4 | Apache-2.0 | https://github.com/RapidAI/RapidOCR |
| recurring-ical-events | 3.8.2 | LGPL-3.0-or-later | https://recurring-ical-events.readthedocs.io/ |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python | https://github.com/mrabarnett/mrab-regex |
| rich | 15.0.0 | MIT License | https://github.com/Textualize/rich |
| safetensors | 0.8.0 | Apache Software License | https://github.com/huggingface/safetensors |
| setuptools | 84.2.1 | MIT | https://github.com/pypa/setuptools |
| shapely | 2.2.0 | BSD-3-Clause | https://github.com/shapely/shapely |
| shellingham | 1.5.4 | ISC License (ISCL) | https://github.com/sarugaku/shellingham |
| six | 1.17.0 | MIT License | https://github.com/benjaminp/six |
| starlette | 1.9.0 | BSD-3-Clause | https://github.com/Kludex/starlette |
| sympy | 1.14.0 | BSD License | https://sympy.org |
| tld | 0.13.2 | MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later | https://github.com/barseghyanartur/tld/ |
| tokenizers | 0.23.3 | Apache Software License | https://github.com/huggingface/tokenizers |
| torch | 2.14.1 | Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT | https://pytorch.org |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | https://tqdm.github.io |
| trafilatura | 2.3.1 | Apache-2.0 | https://trafilatura.readthedocs.io |
| transformers | 5.20.2 | Apache 2.0 License | https://github.com/huggingface/transformers |
| triton | 3.8.0 | MIT | https://github.com/triton-lang/triton/ |
| truststore | 0.10.5 | MIT | https://github.com/sethmlarson/truststore |
| typer | 0.27.3 | MIT | https://github.com/fastapi/typer |
| typing-extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| typing-inspection | 0.4.4 | MIT | https://github.com/pydantic/typing-inspection |
| tzdata | 2026.5 | Apache-2.0 | https://github.com/python/tzdata |
| tzlocal | 5.4.5 | MIT | https://github.com/regebro/tzlocal |
| urllib3 | 2.8.0 | MIT | https://pypi.org/project/urllib3/ |
| uvicorn | 0.54.0 | BSD-3-Clause | https://uvicorn.dev/ |
| x-wr-timezone | 2.0.1 | GNU Lesser General Public License v3 or later (LGPLv3+) | https://github.com/niccokunzmann/x-wr-timezone |
| xlsxwriter | 3.3.0 | BSD-2-Clause | https://github.com/jmcnamara/XlsxWriter |

## 7. The character images

The images of the character (`desktop/src/shared/ui/moods/*.png` and `docs/site/img/*.png`) were created by the author with the AI 3D tool **Meshy** (https://www.meshy.ai), on its **free plan**,
whose outputs are offered under **Creative Commons Attribution 4.0 (CC BY 4.0)**, https://creativecommons.org/licenses/by/4.0/. That license asks for credit, so:
**"Created with Meshy"** (https://www.meshy.ai). The character itself is a tribute, see the note at the end of this file.

## 8. Desktop (Node) packages

`electron` (MIT) is shipped as described in section 1. `electron-builder` (MIT) is a build tool and is not shipped.

---

Independent, free project, with no official connection to TV Cultura, to the program Castelo Rá-Tim-Bum or to the estate of Cláudio Chakmati. It is a tribute to the program's character. The Chakmati character, its name and the universe of the program belong to their rights holders: this project claims no right over the character, only over its own code and the images created by the author, and was made with no intention of discrediting the character or its rights holders. I am open to contact: if the owner of the rights to the character wishes the tribute to be removed, just let me know through the repository's Issues (https://github.com/gregsvieira/chakmati/issues) or my GitHub profile (https://github.com/gregsvieira), and I will honor the request.
Projeto independente e gratuito, sem vínculo oficial com a TV Cultura, com o programa Castelo Rá-Tim-Bum ou com o espólio de Cláudio Chakmati. É uma homenagem ao personagem do programa. O personagem Chakmati, o seu nome e o universo do programa pertencem aos seus titulares: este projeto não reivindica nenhum direito sobre o personagem, só sobre o próprio código e sobre as imagens criadas pelo autor, e foi feito sem qualquer intenção de descrédito ao personagem ou aos seus titulares. Estou aberto ao contato: se a proprietária dos direitos do personagem quiser que a homenagem seja removida, basta me avisar pelas Issues do repositório (https://github.com/gregsvieira/chakmati/issues) ou pelo meu perfil no GitHub (https://github.com/gregsvieira), e eu atendo ao pedido.
