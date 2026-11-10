"""Генератор PDF-звіту ЛР10: збирає дані, будує HTML і друкує PDF."""

import argparse
import json
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

import pymupdf

from html_tools import CSS, EDGE, PDF_PATH, REPORT_DIR, Numbering
from measurements import Package, Quality, load_ci, package, quality
from sections import (
    api_section,
    ci_section,
    configuration_section,
    docker_section,
    packaging_section,
    project_section,
    quality_section,
    release_section,
    title_page,
)


def measured(venv: Path, cache: Path | None) -> tuple[Quality, Package]:
    """Вимірювання; за --cache результат зберігається для швидких правок."""
    if cache is not None and cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        return Quality(**data["quality"]), Package(**data["package"])
    checks, pack = quality(venv), package(venv)
    if cache is not None:
        payload = {"quality": asdict(checks), "package": asdict(pack)}
        cache.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
    return checks, pack


def build_html(venv: Path, cache: Path | None = None) -> str:
    """Збирає повний HTML звіту з виміряних даних."""
    n = Numbering()
    ci = load_ci()
    checks, pack = measured(venv, cache)
    parts = [
        title_page(),
        *project_section(n),
        *packaging_section(pack),
        *configuration_section(checks),
        *docker_section(ci, n),
        *api_section(pack, n),
        *ci_section(ci, n),
        *quality_section(checks),
        *release_section(checks, pack, ci, n),
    ]
    body = "\n".join(parts)
    return (
        "<!doctype html><html lang='uk'><head><meta charset='utf-8'>"
        f"<title>Звіт ЛР10</title><style>{CSS}</style></head>"
        f"<body>{body}</body></html>"
    )


def print_pdf(html_path: Path, pdf_path: Path, profile: Path) -> None:
    """Друкує HTML у PDF через Microsoft Edge."""
    args = [
        str(EDGE),
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--print-to-pdf-no-header",
        f"--user-data-dir={profile}",
        f"--print-to-pdf={pdf_path}",
        html_path.as_uri(),
    ]
    subprocess.run(args, check=True, capture_output=True, timeout=180)


def main() -> None:
    """Будує report.html і Звіт_ЛР10_Левандівський.pdf."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--venv", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(tempfile.gettempdir()) / "lab10_report_edge_profile",
    )
    args = parser.parse_args()
    html_path = REPORT_DIR / "report.html"
    html_path.write_text(build_html(args.venv, args.cache), encoding="utf-8")
    if PDF_PATH.exists():
        PDF_PATH.unlink()
    print_pdf(html_path, PDF_PATH, args.profile)
    with pymupdf.open(PDF_PATH) as document:
        pages = document.page_count
    print(f"PDF: {PDF_PATH} — {pages} сторінок")


if __name__ == "__main__":
    main()
