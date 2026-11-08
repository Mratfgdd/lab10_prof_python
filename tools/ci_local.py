"""Локальний прогін GitHub Actions workflow (.github/workflows/ci.yml).

Виконує ті самі кроки run, що й GitHub: job quality - у чистих контейнерах
python:<версія>-slim для кожної версії з matrix, job docker - на хості з Docker (WSL).
Без Docker job quality виконується в чистій копії проєкту з новим venv у Linux (WSL),
а job docker пропускається. Кроки uses емулюються: checkout - копія файлів проєкту без
ігнорованих каталогів, setup-python - Python образу/venv, upload-artifact - копія файлів.

Запуск у Windows (WSL Debian): python tools/ci_local.py
"""

import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
OUT = ROOT / ".ci-local"
DISTRO = "Debian"
WORK = "$HOME/.cache/bank-ci/work"
VENV = "$HOME/.cache/bank-ci/venv"
EXCLUDE = [
    ".venv",
    ".ci-local",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "htmlcov",
    ".coverage",
    ".env",
    "*.db",
    "*.egg-info",
    "__pycache__",
    "report",
    "*.pdf",
]
MARK = re.compile(r"^::(step|ok|fail|skip)::(.*?)::(\d+)$")


def linux_path(path: Path) -> str:
    drive, rest = path.drive.rstrip(":").lower(), path.as_posix().split(":", 1)[1]
    return f"/mnt/{drive}{rest}"


@dataclass
class Step:
    name: str
    status: str = "pending"
    millis: int = 0


@dataclass
class Run:
    title: str
    steps: list[Step] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return all(step.status in ("ok", "skip") for step in self.steps)


def expand(text: str, matrix: dict[str, str]) -> str:
    def value(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        if expression.startswith("matrix."):
            return matrix[expression.removeprefix("matrix.")]
        if expression.startswith("secrets."):
            return os.environ.get(expression.removeprefix("secrets."), "")
        raise ValueError(f"непідтримуваний вираз: {expression}")

    return re.sub(r"\$\{\{(.*?)\}\}", value, text)


def condition(expression: str | None, matrix: dict[str, str]) -> str:
    """bash-умова для if кроку: always() або порівняння з matrix."""
    if expression is None:
        return '[ "$failed" = 0 ]'
    if expression.strip() == "always()":
        return "true"
    match = re.fullmatch(r"\s*matrix\.([\w-]+)\s*==\s*'([^']*)'\s*", expression)
    if match is None:
        raise ValueError(f"непідтримувана умова: {expression}")
    return '[ "$failed" = 0 ]' if matrix[match.group(1)] == match.group(2) else "false"


def copy_project(source: str, target: str) -> str:
    excludes = " ".join(f"--exclude={shlex.quote(p)}" for p in EXCLUDE)
    return (
        f"rm -rf {target} && mkdir -p {target} && tar -C {source} {excludes} -cf - . "
        f"| tar -C {target} -xf - && ls {target}"
    )


def script(job: dict[str, Any], matrix: dict[str, str], workdir: str, mode: str) -> str:
    """mode: container - чистий контейнер python:<версія>-slim; venv - чиста копія проєкту
    і нове venv у Linux (WSL), коли Docker недоступний; host - каталог проєкту."""
    lines = ["failed=0", f"cd {workdir} 2>/dev/null || true"]
    if mode == "venv":
        lines.append(f"export PATH={VENV}/bin:$PATH")
    for key, value in job.get("env", {}).items():
        lines.append(f"export {key}={shlex.quote(expand(str(value), matrix))}")
    for step in job["steps"]:
        name = step.get("name", step.get("uses", "step"))
        uses = step.get("uses", "")
        if uses.startswith("actions/checkout"):
            body = {
                "container": copy_project("/src", "/work"),
                "venv": copy_project(linux_path(ROOT), workdir),
            }.get(mode, "pwd")
        elif uses.startswith("actions/setup-python"):
            body = (
                f"rm -rf {VENV} && python3 -m venv {VENV} && python --version"
                if mode == "venv"
                else "python --version"
            )
        elif uses.startswith("actions/upload-artifact"):
            target = f"/artifacts/{step['with']['name']}-py{matrix.get('python-version', '')}"
            body = f"mkdir -p {target} && cp -r {step['with']['path']}* {target}/ && ls {target}"
        else:
            body = expand(step["run"], matrix)
        env = "".join(
            f"export {k}={shlex.quote(expand(str(v), matrix))}\n"
            for k, v in step.get("env", {}).items()
        )
        quoted = name.replace("::", ":")
        lines.append(textblock(quoted, condition(step.get("if"), matrix), env + body, workdir))
    lines.append('exit "$failed"')
    return "\n".join(lines) + "\n"


def textblock(name: str, guard: str, body: str, workdir: str) -> str:
    return f"""
if {guard}; then
  echo "::step::{name}::0"; s=$(date +%s%N)
  if ( set -eo pipefail; cd {workdir} 2>/dev/null || true
{body}
  ); then echo "::ok::{name}::$(( ($(date +%s%N) - s) / 1000000 ))"
  else failed=1; echo "::fail::{name}::$(( ($(date +%s%N) - s) / 1000000 ))"; fi
else
  echo "::skip::{name}::0"
fi"""


def execute(title: str, command: list[str], text: str, log: Path) -> Run:
    run = Run(title)
    current: dict[str, Step] = {}
    started = time.perf_counter()
    with (
        log.open("w", encoding="utf-8") as handle,
        subprocess.Popen(  # noqa: S603
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        ) as process,
    ):
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("немає каналів stdin/stdout")
        process.stdin.write(text.encode("utf-8"))
        process.stdin.close()
        for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
            handle.write(line)
            match = MARK.match(line.strip())
            if match:
                kind, name, millis = match.groups()
                step = current.setdefault(name, Step(name))
                if step not in run.steps:
                    run.steps.append(step)
                step.status = {"step": "running"}.get(kind, kind)
                step.millis = int(millis)
                print(
                    f"[{title}] {kind.upper():4} {name}"
                    + (f" ({int(millis) / 1000:.1f} s)" if kind != "step" else ""),
                    flush=True,
                )
    run.seconds = time.perf_counter() - started
    return run


def wsl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["wsl.exe", "-d", DISTRO, "--", *args],  # noqa: S607
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def main() -> int:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    (OUT / "logs").mkdir(parents=True, exist_ok=True)
    (OUT / "artifacts").mkdir(parents=True, exist_ok=True)
    project, artifacts = linux_path(ROOT), linux_path(OUT / "artifacts")
    if wsl("docker", "version").returncode != 0:
        return main_without_docker(workflow)
    runs: list[Run] = []
    for job_id, job in workflow["jobs"].items():
        if any(not r.ok for r in runs):
            print(f"[{job_id}] пропущено: попередній job не пройшов")
            break
        combos = job.get("strategy", {}).get("matrix", {}).get("python-version") or [None]
        for version in combos:
            matrix = {"python-version": version} if version else {}
            title = f"{job_id} (Python {version})" if version else job_id
            log = OUT / "logs" / f"{job_id}{'-' + version if version else ''}.log"
            if version:
                command = [
                    "wsl.exe",
                    "-d",
                    DISTRO,
                    "--",
                    "docker",
                    "run",
                    "-i",
                    "--rm",
                    "-v",
                    f"{project}:/src:ro",
                    "-v",
                    f"{artifacts}:/artifacts",
                    f"python:{version}-slim",
                    "bash",
                    "-s",
                ]
                text = script(job, matrix, "/work", mode="container")
            else:
                sha = os.environ.get("GITHUB_SHA", "local") + "0000000"
                command = ["wsl.exe", "-d", DISTRO, "--", "env", f"GITHUB_SHA={sha}", "bash", "-s"]
                text = script(job, matrix, project, mode="host")
            runs.append(execute(title, command, text, log))
    return summary(runs)


def main_without_docker(workflow: dict[str, Any]) -> int:
    """Docker недоступний: job quality - у чистій копії проєкту з новим venv у Linux (WSL)
    з тим Python, що є в системі; job docker позначається як пропущений."""
    version = wsl("python3", "-c", "import sys; print('%d.%d' % sys.version_info[:2])")
    python = version.stdout.strip()
    print(f"Docker недоступний: job quality - у новому venv, Linux (WSL), Python {python}")
    runs: list[Run] = []
    for job_id, job in workflow["jobs"].items():
        if "strategy" in job:
            command = ["wsl.exe", "-d", DISTRO, "--", "bash", "-s"]
            text = script(job, {"python-version": python}, WORK, mode="venv")
            log = OUT / "logs" / f"{job_id}-linux-py{python}.log"
            runs.append(execute(f"{job_id} (Linux, Python {python}, venv)", command, text, log))
        else:
            skipped = Run(f"{job_id} (пропущено: на ПК немає Docker)")
            skipped.steps = [
                Step(step.get("name", step.get("uses", "step")), "skip") for step in job["steps"]
            ]
            runs.append(skipped)
    return summary(runs)


def summary(runs: list[Run]) -> int:
    print("\nПідсумок локального прогону workflow CI:")
    for run in runs:
        mark = "✓" if run.ok else "✗"
        print(f"{mark} {run.title}: {len(run.steps)} кроків, {run.seconds:.0f} с")
        for step in run.steps:
            symbol = {"ok": "✓", "fail": "✗", "skip": "–"}.get(step.status, "?")
            print(f"    {symbol} {step.name:<42} {step.millis / 1000:6.1f} с")
    return 0 if runs and all(run.ok for run in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
