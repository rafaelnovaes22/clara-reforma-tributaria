from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MINIMUM_PYTHON = (3, 12)
MINIMUM_NODE_MAJOR = 22
VENV_PATH = ROOT / ".venv"
NPM_CACHE_PATH = ROOT / ".npm-cache"


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def virtualenv_python() -> Path:
    executable = "python.exe" if os.name == "nt" else "python"
    scripts_folder = "Scripts" if os.name == "nt" else "bin"
    return VENV_PATH / scripts_folder / executable


def npm_executable() -> str:
    executable = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not executable:
        raise RuntimeError("npm não foi encontrado; instale Node.js 22 ou superior.")
    return executable


def validate_node() -> None:
    executable = shutil.which("node.exe" if os.name == "nt" else "node")
    if not executable:
        raise RuntimeError("Node.js não foi encontrado; instale a versão 22 ou superior.")
    version = subprocess.check_output([executable, "--version"], text=True).strip()
    major = int(version.removeprefix("v").split(".", 1)[0])
    if major < MINIMUM_NODE_MAJOR:
        raise RuntimeError(f"Node.js {version} detectado; o piloto exige a versão 22 ou superior.")


def run_command(arguments: list[str]) -> None:
    emit("setup_command", command=arguments[0], arguments=arguments[1:])
    subprocess.run(arguments, cwd=ROOT, check=True)


def validate_python() -> None:
    current_python = (sys.version_info.major, sys.version_info.minor)
    if current_python < MINIMUM_PYTHON:
        received = ".".join(str(part) for part in sys.version_info[:3])
        raise RuntimeError(f"Python {received} detectado; o piloto exige Python 3.12 ou superior.")


def ensure_virtualenv() -> Path:
    python_path = virtualenv_python()
    if not python_path.is_file():
        emit("virtualenv_create", path=str(VENV_PATH))
        venv.EnvBuilder(with_pip=True).create(VENV_PATH)
    else:
        emit("virtualenv_reuse", path=str(VENV_PATH))
    return python_path


def install_python_dependencies(python_path: Path, production: bool) -> None:
    requirements = "requirements.txt" if production else "requirements-dev.txt"
    run_command(
        [
            str(python_path),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--requirement",
            requirements,
        ]
    )
    run_command([str(python_path), "-m", "pip", "check"])


def install_frontend_dependencies() -> None:
    run_command([npm_executable(), "ci", "--prefix", "frontend", "--cache", str(NPM_CACHE_PATH)])
    run_command([npm_executable(), "run", "build", "--prefix", "frontend"])


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Setup idempotente da Clara.")
    parser.add_argument("--production", action="store_true", help="Instala somente dependências do servidor.")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    validate_python()
    python_path = ensure_virtualenv()
    install_python_dependencies(python_path, arguments.production)
    if not arguments.production:
        validate_node()
        install_frontend_dependencies()
    emit("setup_complete", python=str(python_path), production=arguments.production)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
