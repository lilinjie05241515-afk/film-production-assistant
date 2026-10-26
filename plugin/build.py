"""Build a portable payload without editing host configuration."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release.assemble import assemble

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New payload directory")
    args = parser.parse_args()
    print(json.dumps(assemble(Path(__file__).resolve().parents[1], args.output), ensure_ascii=False))
