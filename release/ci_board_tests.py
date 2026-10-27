"""Run every checked-in board test without platform-dependent shell globbing."""
from pathlib import Path
import subprocess

source = Path(__file__).resolve().parents[1]
tests = sorted(str(p.relative_to(source)) for p in (source / "tests").glob("test_*.cjs"))
if not tests:
    raise SystemExit("No board interaction tests found")
raise SystemExit(subprocess.call(["node", "--test", *tests], cwd=source))
