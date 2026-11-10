"""Спільні засоби генератора звіту: HTML-примітиви, запуск команд, Edge."""

import ast
import base64
import html
import os
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "report"
RESULTS = ROOT / "results"
SRC = ROOT / "src" / "student_manager"
CAPTURES = REPORT_DIR / "captures"
PDF_PATH = ROOT / "Звіт_ЛР10_Левандівський.pdf"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
PROMPT = r"PS C:\Github\prof_python\Lab_10>"


def esc(text: str) -> str:
    """Екранує текст для HTML."""
    return html.escape(text, quote=False)


def c(text: str) -> str:
    """Фрагмент коду в тексті абзацу."""
    return f"<code>{esc(text)}</code>"


def para(*chunks: str, cls: str = "") -> str:
    """Абзац зі шматків тексту (щоб рядки коду лишалися короткими)."""
    attr = f' class="{cls}"' if cls else ""
    return f"<p{attr}>{' '.join(chunks)}</p>"


def code(source: str, keep: bool | None = None) -> str:
    """Блок коду; короткі блоки не розриваються між сторінками."""
    text = source.strip("\n")
    if keep is None:
        keep = text.count("\n") < 18
    return f'<pre class="code{" keep" if keep else ""}">{esc(text)}</pre>'


def extract(path: Path, *names: str) -> str:
    """Витягує з файлу вихідний код функцій і класів за назвами."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    nodes = {
        node.name: node
        for node in ast.walk(ast.parse(source))
        if isinstance(
            node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
        )
    }
    parts = []
    for name in names:
        node = nodes[name]
        first = min([d.lineno for d in node.decorator_list] + [node.lineno])
        begin, end = first - 1, node.end_lineno
        chunk = "\n".join(lines[begin:end])
        parts.append(textwrap.dedent(chunk))
    return "\n\n".join(parts)


def terminal(command: str, output: str) -> str:
    """Темний блок, що імітує вікно термінала з командою та виводом."""
    return (
        f'<div class="term"><span class="ps">{esc(PROMPT)}</span> '
        f"{esc(command)}\n{esc(output.rstrip())}</div>"
    )


def table(headers: list[str], rows: list[list[str]], cls: str = "") -> str:
    """HTML-таблиця із заголовком."""
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return (
        f'<table class="{cls}"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def figure(content: str, caption: str) -> str:
    """Рисунок із підписом; не розривається між сторінками."""
    return f'<div class="figure">{content}{caption}</div>'


class Numbering:
    """Наскрізна нумерація таблиць і рисунків."""

    def __init__(self) -> None:
        """Починає нумерацію з нуля."""
        self.table = 0
        self.figure = 0

    def tcap(self, text: str) -> str:
        """Підпис таблиці."""
        self.table += 1
        return f'<p class="tcap">Таблиця {self.table} – {text}</p>'

    def fcap(self, text: str) -> str:
        """Підпис рисунка."""
        self.figure += 1
        return f'<p class="fcap">Рисунок {self.figure} – {text}</p>'


def image(path: Path, width: int = 100) -> str:
    """PNG-файл як вбудований тег img (base64)."""
    data = base64.b64encode(path.read_bytes()).decode()
    return (
        f'<img src="data:image/png;base64,{data}" alt="{path.stem}" '
        f'style="width: {width}%">'
    )


def run_program(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Запускає програму з кореня проєкту; вивід у UTF-8."""
    return subprocess.run(
        command,
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        errors="replace",
        encoding="utf-8",
        cwd=ROOT,
    )


def run(venv: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Запускає python -m ... в інтерпретаторі venv."""
    interpreter = venv / "Scripts" / "python.exe"
    return run_program([str(interpreter), "-m", *args])


def plural(count: int, one: str, few: str, many: str) -> str:
    """Форма слова за українськими правилами: 1 рядок, 2 рядки, 5 рядків."""
    last_two, last = count % 100, count % 10
    if last == 1 and last_two != 11:
        return f"{count} {one}"
    if 2 <= last <= 4 and not 12 <= last_two <= 14:
        return f"{count} {few}"
    return f"{count} {many}"


def num(value: float, digits: int = 3) -> str:
    """Число з десятковою комою й нерозривним пробілом у тисячах."""
    text = f"{value:,.{digits}f}"
    return text.replace(",", "\u00a0").replace(".", ",")


def last_line(text: str) -> str:
    """Остання непорожня лінія виводу."""
    return text.strip().splitlines()[-1]


CSS = """
@page { size: A4; margin: 20mm 15mm 20mm 30mm;
  @bottom-center { content: counter(page);
    font: 12pt "Times New Roman", serif; } }
@page :first { @bottom-center { content: none; } }
html { background: #fff; }
body { margin: 0; color: #000; background: #fff;
  font-family: "Times New Roman", serif; font-size: 14pt;
  line-height: 1.22; }
p { margin: 0 0 2pt; text-indent: 1.25cm; text-align: justify; }
h1 { font-size: 14pt; text-align: center; margin: 9pt 0 4pt;
  break-after: avoid; }
code { font-family: Consolas, "Courier New", monospace; font-size: 0.8em; }
pre.code { font-family: Consolas, "Courier New", monospace;
  font-size: 7.9pt; line-height: 1.12; margin: 2pt 0 5pt;
  padding: 3pt 8pt; white-space: pre-wrap; background: #f6f6f4;
  border-left: 3px solid #c3c2b7; orphans: 4; widows: 4; }
pre.keep { break-inside: avoid; }
.term { font-family: Consolas, "Courier New", monospace; font-size: 7.3pt;
  line-height: 1.13; white-space: pre-wrap; background: #0c0c0c;
  color: #d4d4d4; padding: 4pt 8pt; border-radius: 4px;
  margin: 2pt 0 3pt; break-inside: avoid; text-align: left; }
.term .ps { color: #f9f1a5; }
table { width: 100%; border-collapse: collapse; font-size: 10pt;
  line-height: 1.12; margin: 2pt 0 5pt; }
th, td { border: 1px solid #000; padding: 1.2pt 3.5pt; vertical-align: top;
  text-align: left; }
th { background: #f0efec; }
td.n, th.n { text-align: right; }
tr { break-inside: avoid; }
p.lead { break-after: avoid; }
.tcap { text-indent: 0; text-align: left; margin: 4pt 0 2pt;
  break-after: avoid; }
.fcap { text-indent: 0; text-align: center; margin: 1pt 0 5pt; }
.figure { break-inside: avoid; margin-top: 3pt; text-align: center; }
.figure svg { width: 100%; height: auto; }
.title { height: 255mm; display: flex; flex-direction: column;
  justify-content: space-between; text-align: center; break-after: page;
  line-height: 1.5; }
.title .main { margin-top: 30mm; }
.title .main .big { font-size: 20pt; font-weight: bold;
  letter-spacing: 2pt; }
.title .main .theme { font-size: 16pt; font-weight: bold; margin-top: 10pt; }
.title .sign { align-self: flex-end; text-align: left; width: 85mm;
  margin-top: 30mm; }
.title .city { margin-top: auto; }
"""
