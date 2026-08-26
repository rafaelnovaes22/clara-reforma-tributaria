from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON_TARGETS = ["backend", "evals", "scripts", "tests"]
SOURCE_TARGETS = [*PYTHON_TARGETS, "frontend"]
SOURCE_SUFFIXES = {".css", ".html", ".js", ".py", ".ts"}
IGNORED_PARTS = {".venv", "node_modules"}
MAX_FUNCTION_LINES = 20
MAX_SOURCE_LINES = 500


def run_command(arguments: list[str], environment: dict[str, str] | None = None) -> None:
    print(json.dumps({"event": "verify_command", "command": arguments}, ensure_ascii=False), flush=True)
    subprocess.run(arguments, cwd=ROOT, env=environment, check=True)


def validate_json_files() -> None:
    for path in sorted(ROOT.rglob("*.json")):
        if "node_modules" in path.parts or ".venv" in path.parts:
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"JSON inválido em {path}: {exc}.") from exc
    validate_railway_contract()


def validate_railway_contract() -> None:
    manifest = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
    deployment: dict[str, Any] = manifest.get("deploy", {})
    expected = {
        "startCommand": "python -u backend/server.py",
        "healthcheckPath": "/api/ready",
        "numReplicas": 1,
    }
    mismatches = [key for key, value in expected.items() if deployment.get(key) != value]
    if mismatches:
        raise RuntimeError(f"railway.json diverge do contrato do piloto: {', '.join(mismatches)}.")


def owned_source_paths() -> list[Path]:
    paths = [path for target in SOURCE_TARGETS for path in (ROOT / target).rglob("*")]
    return sorted(
        path
        for path in paths
        if path.is_file() and path.suffix in SOURCE_SUFFIXES and not IGNORED_PARTS.intersection(path.parts)
    )


def python_function_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    return [
        f"{path.relative_to(ROOT)}:{node.lineno} ({node.name}, {node.end_lineno - node.lineno + 1} linhas)"
        for node in ast.walk(tree)
        if isinstance(node, functions) and node.end_lineno and node.end_lineno - node.lineno + 1 > MAX_FUNCTION_LINES
    ]


def structure_violations() -> list[str]:
    paths = owned_source_paths()
    oversized = [
        f"{path.relative_to(ROOT)} ({len(path.read_text(encoding='utf-8').splitlines())} linhas)"
        for path in paths
        if len(path.read_text(encoding="utf-8").splitlines()) > MAX_SOURCE_LINES
    ]
    long_functions = [item for path in paths if path.suffix == ".py" for item in python_function_violations(path)]
    return [*[f"arquivo: {item}" for item in oversized], *[f"função: {item}" for item in long_functions]]


def validate_structure_limits() -> None:
    violations = structure_violations()
    if violations:
        raise RuntimeError("Limites estruturais excedidos:\n" + "\n".join(violations))


def typescript_compiler() -> Path:
    executable = "tsc.cmd" if os.name == "nt" else "tsc"
    path = ROOT / "frontend" / "node_modules" / ".bin" / executable
    if not path.is_file():
        raise RuntimeError(f"Compilador TypeScript ausente em {path}; execute python scripts/setup.py.")
    return path


def environment_executable(name: str) -> str:
    suffix = ".exe" if os.name == "nt" else ""
    beside_python = Path(sys.executable).parent / f"{name}{suffix}"
    discovered = shutil.which(name)
    if beside_python.is_file():
        return str(beside_python)
    if discovered:
        return discovered
    raise RuntimeError(f"Executável {name} não encontrado; execute python scripts/setup.py.")


def verify_compiled_frontend() -> None:
    with tempfile.TemporaryDirectory(prefix="clara-ts-") as temporary_directory:
        output_path = Path(temporary_directory) / "app.js"
        run_command(typescript_build_command(output_path))
        committed_output = (ROOT / "frontend" / "app.js").read_bytes()
        if output_path.read_bytes() != committed_output:
            raise RuntimeError("frontend/app.js está desatualizado; execute npm run build --prefix frontend.")


def typescript_build_command(output_path: Path) -> list[str]:
    return [
        str(typescript_compiler()),
        "--target",
        "ES2022",
        "--module",
        "none",
        "--strict",
        "--lib",
        "DOM,ES2022",
        "--removeComments",
        "--outFile",
        str(output_path),
        "frontend/runtime.ts",
        "frontend/app.ts",
    ]


def verify_langgraph() -> None:
    run_command(
        [
            sys.executable,
            "-c",
            "from backend.clara.conversation import LANGGRAPH_AVAILABLE; assert LANGGRAPH_AVAILABLE",
        ]
    )


def main() -> int:
    ruff = environment_executable("ruff")
    run_command([ruff, "format", "--check", *PYTHON_TARGETS])
    run_command([ruff, "check", *PYTHON_TARGETS])
    run_command([sys.executable, "-m", "compileall", "-q", *PYTHON_TARGETS])
    run_command(["npm.cmd" if os.name == "nt" else "npm", "run", "check", "--prefix", "frontend"])
    run_command(["npm.cmd" if os.name == "nt" else "npm", "run", "format:check", "--prefix", "frontend"])
    verify_compiled_frontend()
    validate_json_files()
    validate_structure_limits()
    run_command([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"])
    eval_environment = {**os.environ, "CLARA_EVAL_NO_WRITE": "1"}
    run_command([sys.executable, "evals/run_evals.py"], eval_environment)
    run_command([sys.executable, "evals/run_conversation_evals.py"], eval_environment)
    verify_langgraph()
    print(json.dumps({"event": "verify_complete", "status": "passed"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
