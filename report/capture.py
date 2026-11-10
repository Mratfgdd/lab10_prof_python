"""Збір зовнішніх доказів для звіту: GitHub Actions, знімки Edge, git log.

python report/capture.py --repo <клон із репозиторієм> --venv <venv> [--run ID]
Результати кладуться в report/captures і потім використовуються build_report.
"""

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image

from html_tools import CAPTURES, EDGE, ROOT, run_program

REPOSITORY = "Mratfgdd/lab10_prof_python"
API = f"https://api.github.com/repos/{REPOSITORY}/actions"
PAGE = f"https://github.com/{REPOSITORY}/actions/runs"


def api(path: str) -> dict[str, Any]:
    """GET до GitHub API без авторизації (репозиторій публічний)."""
    request = urllib.request.Request(
        API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "lab10-report",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data: dict[str, Any] = json.load(response)
    return data


def seconds(start: str, end: str) -> int:
    """Тривалість між двома ISO-часами GitHub у секундах."""
    stamp = "%Y-%m-%dT%H:%M:%SZ"
    delta = time.mktime(time.strptime(end, stamp))
    return int(delta - time.mktime(time.strptime(start, stamp)))


def collect_ci(run_id: int | None) -> dict[str, Any]:
    """Запуск workflow, його jobs і кроки з тривалістю."""
    if run_id is None:
        runs = api("/runs?branch=main&status=success&per_page=1")
        run_id = int(runs["workflow_runs"][0]["id"])
    info = api(f"/runs/{run_id}")
    jobs = []
    for job in api(f"/runs/{run_id}/jobs")["jobs"]:
        steps = [
            {
                "name": step["name"],
                "conclusion": step["conclusion"],
                "seconds": seconds(step["started_at"], step["completed_at"]),
            }
            for step in job["steps"]
            if not step["name"].startswith(("Post ", "Set up job", "Complete"))
        ]
        jobs.append(
            {
                "id": job["id"],
                "name": job["name"],
                "conclusion": job["conclusion"],
                "seconds": seconds(job["started_at"], job["completed_at"]),
                "steps": steps,
            }
        )
    return {
        "run_id": run_id,
        "number": info["run_number"],
        "url": info["html_url"],
        "sha": info["head_sha"],
        "title": info["display_title"],
        "conclusion": info["conclusion"],
        "event": info["event"],
        "jobs": jobs,
    }


def screenshot(url: str, target: Path, width: int, height: int) -> None:
    """Знімок сторінки в headless Edge (з очікуванням завантаження)."""
    target.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        subprocess.run(
            [
                str(EDGE),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--force-device-scale-factor=1.3",
                f"--window-size={width},{height}",
                "--virtual-time-budget=25000",
                f"--user-data-dir={profile}",
                f"--screenshot={target}",
                url,
            ],
            check=False,
            capture_output=True,
            timeout=180,
        )
    if not target.exists() or target.stat().st_size == 0:
        raise RuntimeError(f"Edge не створив знімок {target.name}")


def crop(target: Path, top: float, bottom: float, right: float = 1.0) -> None:
    """Залишає в знімку смугу між top і bottom та ліву частину до right."""
    with Image.open(target) as source:
        width, height = source.size
        box = (0, int(height * top), int(width * right), int(height * bottom))
        strip = source.crop(box)
        strip.save(target)


def free_port() -> int:
    """Вільний локальний порт."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def swagger_screenshot(venv: Path, target: Path) -> None:
    """Запускає сервер із тимчасовою БД і знімає його /docs."""
    program = venv / "Scripts" / "student-manager.exe"
    port = free_port()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        env = {
            **os.environ,
            "ENVIRONMENT": "production",
            "DATABASE_URL": f"sqlite:///{Path(folder) / 'students.db'}",
        }
        with subprocess.Popen(
            [str(program), "serve", "--port", str(port)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ) as server:
            try:
                wait_for_server(port)
                screenshot(f"http://127.0.0.1:{port}/docs", target, 1100, 900)
            finally:
                subprocess.run(
                    ["taskkill", "/PID", str(server.pid), "/T", "/F"],
                    check=False,
                    capture_output=True,
                )
                server.wait(timeout=15)


def wait_for_server(port: int) -> None:
    """Чекає, поки /health відповість 200."""
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            url = f"http://127.0.0.1:{port}/health"
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.4)
    raise RuntimeError("сервер не запустився")


def git_log(repo: Path) -> str:
    """Коміти клону від найстарішого до найновішого (хеш і тема)."""
    done = run_program(
        ["git", "-C", str(repo), "log", "--reverse", "--format=%h %s"]
    )
    if done.returncode:
        raise RuntimeError(done.stderr)
    return done.stdout.strip()


def main() -> None:
    """Збирає всі докази в report/captures."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--venv", type=Path, required=True)
    parser.add_argument("--run", type=int)
    args = parser.parse_args()
    CAPTURES.mkdir(exist_ok=True)
    ci = collect_ci(args.run)
    (CAPTURES / "ci.json").write_text(
        json.dumps(ci, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    screenshot(ci["url"], CAPTURES / "run.png", 1280, 1500)
    crop(CAPTURES / "run.png", 0.10, 0.44)
    docker = next(
        job for job in ci["jobs"] if job["name"].startswith("Docker")
    )
    screenshot(
        f"{PAGE}/{ci['run_id']}/job/{docker['id']}",
        CAPTURES / "docker_job.png",
        1280,
        1100,
    )
    crop(CAPTURES / "docker_job.png", 0.34, 1.0, 0.62)
    swagger_screenshot(args.venv, CAPTURES / "swagger.png")
    log = git_log(args.repo)
    (CAPTURES / "git_log.txt").write_text(log + "\n", encoding="utf-8")
    print(
        f"run #{ci['number']} {ci['conclusion']}, commits: "
        f"{len(log.splitlines())}"
    )
    print(ROOT)


if __name__ == "__main__":
    main()
