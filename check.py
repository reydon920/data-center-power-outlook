"""Run both parts' checks from the repository root.

    python check.py              run the heat and grid queue test suites
    python check.py --showcase   regenerate both parts' showcase images

Each part uses its own .venv when it has one, otherwise the Python running this script.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTS = {"heat": ["-m", "unittest", "-v"], "grid_queue": ["-m", "pytest", "-q"]}
SHOWCASE = {"heat": ["-m", "heat_exposure", "--showcase", "docs/showcase"],
            "grid_queue": ["-m", "showcase", "--showcase", "docs/showcase"]}


def python_for(part: Path) -> str:
    for candidate in (part / ".venv" / "Scripts" / "python.exe", part / ".venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def main() -> int:
    steps = SHOWCASE if "--showcase" in sys.argv[1:] else TESTS
    failed = []
    for name, args in steps.items():
        part = ROOT / name
        print(f"== {name}: python {' '.join(args)}", flush=True)
        if subprocess.run([python_for(part), *args], cwd=part).returncode:
            failed.append(name)
    print("Failed: " + ", ".join(failed) if failed else "All checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
