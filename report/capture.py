"""Збирає живі результати для звіту ЛР10 у report/captures/.

Запуск з каталогу Lab_10 (Windows, WSL Debian):  .venv\\Scripts\\python report\\capture.py

1. python -m build і вміст dist/ (Windows).
2. Локальний прогін workflow CI: tools/ci_local.py (job quality - Linux/WSL, нове venv).
3. Перевірка runtime-етапу Dockerfile без Docker (на ПК Docker не встановлено): wheel із
   dist/ встановлюється в нове venv у Linux (WSL), змінні середовища - як ENV у Dockerfile і
   --env-file, запуск - як CMD (serve), перевірка - командою HEALTHCHECK і запитами curl;
   знімок Swagger UI робить Microsoft Edge (headless) з Windows.
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPTURES = ROOT / "report" / "captures"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
WHEEL = "bank_account_service-1.0.0-py3-none-any.whl"
DISTRO = "Debian"
PORT = 8000

LINUX_STEPS: list[tuple[str, str]] = [
    ("python3 --version", "python3 --version"),
    ("python3 -m venv venv && . venv/bin/activate", "python3 -m venv venv && . venv/bin/activate"),
    (f"pip install {WHEEL} | tail -n 1",
     f"pip install --disable-pip-version-check {WHEEL} | tail -n 1"),
    ("bank-account-service --version", "bank-account-service --version"),
    ("export APP_ENV=production LOG_LEVEL=INFO DATABASE_URL=sqlite:///$HOME/bank/data/bank.db",
     "export APP_ENV=production LOG_LEVEL=INFO DATABASE_URL=sqlite:///$HOME/bank/data/bank.db"),
    ("set -a; . ./bank.env; set +a      # API_TOKEN - з файла поза Git (як --env-file)",
     "set -a; . ./bank.env; set +a"),
    ("bank-account-service config", "bank-account-service config"),
    (f"bank-account-service serve --host 0.0.0.0 --port {PORT} > serve.log 2>&1 & SERVER_PID=$!",
     f"bank-account-service serve --host 0.0.0.0 --port {PORT} > serve.log 2>&1 & SERVER_PID=$!\n"
     f"for i in $(seq 1 150); do curl -sf localhost:{PORT}/health > /dev/null && break; "
     "sleep 0.1; done"),
    ("cat serve.log", "cat serve.log"),
    ("python -c \"import sys, urllib.request; sys.exit(urllib.request.urlopen("
     f"'http://127.0.0.1:{PORT}/health', timeout=2).status != 200)\"; echo \"exit code: $?\"",
     "python -c \"import sys, urllib.request; sys.exit(urllib.request.urlopen("
     f"'http://127.0.0.1:{PORT}/health', timeout=2).status != 200)\"; echo \"exit code: $?\""),
    (f"curl -s localhost:{PORT}/health", f"curl -s localhost:{PORT}/health; echo"),
    (f"curl -s -w ' HTTP %{{http_code}}\\n' -X POST localhost:{PORT}/clients "
     "-H 'Content-Type: application/json' -d '{\"full_name\": \"Олена Коваленко\"}'",
     f"curl -s -w ' HTTP %{{http_code}}\\n' -X POST localhost:{PORT}/clients "
     "-H 'Content-Type: application/json' -d '{\"full_name\": \"Олена Коваленко\"}'"),
    ("api() { curl -s -w ' HTTP %{http_code}\\n' -H 'Content-Type: application/json' "
     "-H \"X-API-Key: $API_TOKEN\" \"$@\"; }",
     "api() { curl -s -w ' HTTP %{http_code}\\n' -H 'Content-Type: application/json' "
     "-H \"X-API-Key: $API_TOKEN\" \"$@\"; }"),
    (f"api -X POST localhost:{PORT}/clients -d '{{\"full_name\": \"Олена Коваленко\"}}'",
     f"api -X POST localhost:{PORT}/clients -d '{{\"full_name\": \"Олена Коваленко\"}}'"),
    (f"api -X POST localhost:{PORT}/clients -d '{{\"full_name\": \"Андрій Мельник\"}}'",
     f"api -X POST localhost:{PORT}/clients -d '{{\"full_name\": \"Андрій Мельник\"}}'"),
    (f"api -X POST localhost:{PORT}/accounts "
     "-d '{\"client_id\": 1, \"number\": \"UA-1001\", \"opening_balance\": \"1000.00\"}'",
     f"api -X POST localhost:{PORT}/accounts "
     "-d '{\"client_id\": 1, \"number\": \"UA-1001\", \"opening_balance\": \"1000.00\"}'"),
    (f"api -X POST localhost:{PORT}/accounts "
     "-d '{\"client_id\": 2, \"number\": \"UA-1002\", \"opening_balance\": \"250.00\"}'",
     f"api -X POST localhost:{PORT}/accounts "
     "-d '{\"client_id\": 2, \"number\": \"UA-1002\", \"opening_balance\": \"250.00\"}'"),
    (f"api -X POST localhost:{PORT}/accounts/1/deposit -d '{{\"amount\": \"500.00\"}}'",
     f"api -X POST localhost:{PORT}/accounts/1/deposit -d '{{\"amount\": \"500.00\"}}'"),
    (f"api -X POST localhost:{PORT}/transfers "
     "-d '{\"source_id\": 1, \"target_id\": 2, \"amount\": \"300.00\"}'",
     f"api -X POST localhost:{PORT}/transfers "
     "-d '{\"source_id\": 1, \"target_id\": 2, \"amount\": \"300.00\"}'"),
    (f"api -X POST localhost:{PORT}/transfers "
     "-d '{\"source_id\": 2, \"target_id\": 1, \"amount\": \"9999.00\"}'",
     f"api -X POST localhost:{PORT}/transfers "
     "-d '{\"source_id\": 2, \"target_id\": 1, \"amount\": \"9999.00\"}'"),
    (f"curl -s 'localhost:{PORT}/accounts/1/transactions'",
     f"curl -s 'localhost:{PORT}/accounts/1/transactions'; echo"),
    (f"curl -s 'localhost:{PORT}/statistics/funds'",
     f"curl -s 'localhost:{PORT}/statistics/funds'; echo"),
    (f"curl -s 'localhost:{PORT}/statistics/interest?currency=UAH&days=365'",
     f"curl -s 'localhost:{PORT}/statistics/interest?currency=UAH&days=365'; echo"),
]
LINUX_AFTER: list[tuple[str, str]] = [
    ("kill $SERVER_PID; wait $SERVER_PID; tail -n 3 serve.log",
     "kill $SERVER_PID; wait $SERVER_PID; tail -n 3 serve.log"),
    (f"bank-account-service serve --port {PORT} > serve2.log 2>&1 & SERVER_PID=$!",
     f"bank-account-service serve --port {PORT} > serve2.log 2>&1 & SERVER_PID=$!\n"
     f"for i in $(seq 1 150); do curl -sf localhost:{PORT}/health > /dev/null && break; "
     "sleep 0.1; done"),
    (f"curl -s 'localhost:{PORT}/accounts?sort=number'",
     f"curl -s 'localhost:{PORT}/accounts?sort=number'; echo"),
    ("kill $SERVER_PID; wait $SERVER_PID; ls -l data", "kill $SERVER_PID; wait $SERVER_PID; ls -l data"),
]


def run(args: list[str], *, cwd: Path = ROOT, ok: tuple[int, ...] = (0,)) -> str:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run(args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False)
    text = done.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
    assert done.returncode in ok, (args, text[-4000:])
    return text


def save(name: str, data: object) -> None:
    (CAPTURES / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  -> captures/{name}")


def capture_build() -> None:
    print("1. python -m build")
    egg_info = ROOT / "src" / "bank_account_service.egg-info"
    had_egg_info = egg_info.exists()
    for folder in ("dist", "build"):
        shutil.rmtree(ROOT / folder, ignore_errors=True)
    build = run([str(PYTHON), "-m", "build"])
    assert "Successfully built bank_account_service-1.0.0.tar.gz and " + WHEEL in build
    dist = run(["powershell.exe", "-NoProfile", "-Command",
                "Get-ChildItem dist | Format-Table Mode, LastWriteTime, Length, Name -AutoSize"
                " | Out-String -Width 120"])
    wheel = run([str(PYTHON), "-m", "zipfile", "-l", f"dist/{WHEEL}"])
    sdist = run(["tar.exe", "-tzf", "dist/bank_account_service-1.0.0.tar.gz"])
    metadata = run([str(PYTHON), "-c",
                    "import zipfile; z = zipfile.ZipFile('dist/" + WHEEL + "'); "
                    "print(z.read('bank_account_service-1.0.0.dist-info/METADATA').decode())"])
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    if not had_egg_info:
        shutil.rmtree(egg_info, ignore_errors=True)
    save("build.json", {"build": build, "dist": dist, "wheel": wheel, "sdist": sdist,
                        "metadata": metadata})


def capture_ci() -> None:
    print("2. tools/ci_local.py")
    output = run([str(PYTHON), "tools/ci_local.py"])
    logs = {path.name: path.read_text(encoding="utf-8")
            for path in (ROOT / ".ci-local" / "logs").glob("*.log")}
    save("ci.json", {"summary": output, "logs": logs})


def linux_script(steps: list[tuple[str, str]], *, setup: bool) -> str:
    lines = ["set -o pipefail", 'BASE="$HOME/bank"']
    if setup:
        lines += [
            'rm -rf "$BASE" && mkdir -p "$BASE" && cd "$BASE" || exit 1',
            f"cp /mnt/c/Github/prof_python/Lab_10/dist/{WHEEL} .",
            "python3 -c \"import secrets; print('API_TOKEN=' + secrets.token_urlsafe(24))\""
            " > bank.env && chmod 600 bank.env",
        ]
    for display, command in steps:
        lines += [f"printf '@@CMD %s\\n' {shlex.quote(display)}", f"{{ {command}\n}} 2>&1",
                  "printf '@@RC %s\\n' \"$?\""]
    return "\n".join(lines) + "\n"


def parse(transcript: str) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    for line in transcript.splitlines():
        if line.startswith("@@CMD "):
            steps.append({"cmd": line[6:], "out": [], "rc": None})
        elif line.startswith("@@RC "):
            steps[-1]["rc"] = int(line[5:])
        elif steps and line != "@@READY":
            out = steps[-1]["out"]
            assert isinstance(out, list)
            out.append(line)
    return [{**s, "out": "\n".join(s["out"])} for s in steps]  # type: ignore[arg-type]


def screenshot(url: str, profile: Path) -> bytes:
    with tempfile.TemporaryDirectory() as folder:
        png = Path(folder) / "shot.png"
        subprocess.run([str(EDGE), "--headless=new", "--disable-gpu", f"--user-data-dir={profile}",
                        "--hide-scrollbars", "--force-device-scale-factor=1.5",
                        "--window-size=1000,1135", "--virtual-time-budget=8000",
                        f"--screenshot={png}", url], check=True, capture_output=True, timeout=120)
        return png.read_bytes()


def capture_linux(profile: Path) -> None:
    print("3. runtime-етап Dockerfile без Docker: Linux (WSL), нове venv")
    script = (linux_script(LINUX_STEPS, setup=True) + "echo @@READY\n"
              'while [ ! -f "$BASE/.screenshot-done" ]; do sleep 0.2; done\n'
              + linux_script(LINUX_AFTER, setup=False).split("\n", 2)[2])
    command = ["wsl.exe", "-d", DISTRO, "--", "bash", "-s"]
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT) as process:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(script.encode("utf-8"))
        process.stdin.close()
        lines: list[str] = []
        for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            lines.append(line)
            if line == "@@READY":
                png = screenshot(f"http://localhost:{PORT}/docs", profile)
                (CAPTURES / "swagger.png").write_bytes(png)
                print(f"  -> captures/swagger.png ({len(png) // 1024} КБ)")
                subprocess.run(["wsl.exe", "-d", DISTRO, "--", "touch",
                                "/home/user/bank/.screenshot-done"], check=True)
        process.wait(timeout=120)
    steps = parse("\n".join(lines))
    failed = [s["cmd"] for s in steps if s["rc"] != 0]
    assert not failed, failed
    run(["wsl.exe", "-d", DISTRO, "--", "rm", "-f", "/home/user/bank/bank.env"])
    save("linux.json", steps)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["build", "ci", "linux"])
    parser.add_argument("--profile", type=Path,
                        default=Path(tempfile.gettempdir()) / "lab10_report_edge_profile")
    args = parser.parse_args()
    CAPTURES.mkdir(parents=True, exist_ok=True)
    if args.only in (None, "build"):
        capture_build()
    if args.only in (None, "ci"):
        capture_ci()
    if args.only in (None, "linux"):
        capture_linux(args.profile)


if __name__ == "__main__":
    main()
