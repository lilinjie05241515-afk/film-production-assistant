"""Local exact-manifest rendering. No server or API key required."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from filmprod.core import Registry
from filmprod.render import render_final


def main():
    parser = argparse.ArgumentParser(description="按精确成片版本在本机渲染，默认严格正式前置检查")
    parser.add_argument("--root", required=True)
    parser.add_argument("--final", required=True, dest="artifact_id")
    parser.add_argument("--version", required=True, type=int)
    parser.add_argument("--op-id", required=True)
    parser.add_argument("--preview", action="store_true", help="明确测试预览，含可见水印且记录所有输入问题")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--ffprobe")
    args = vars(parser.parse_args())
    root = Path(args.pop("root"))
    if not root.is_absolute() or not (root / ".project" / "registry.sqlite3").is_file():
        parser.error("--root 必须为已登记作品的绝对路径；渲染入口不会创建空项目")
    registry = Registry(root)
    try:
        print(json.dumps(render_final(registry, args), ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        registry.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
