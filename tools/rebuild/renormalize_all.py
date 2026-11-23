"""对全部站点重新执行 CSS 前缀剥离（重拷 assets 之后必须补这一步）。"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from batch_rebuild import OUTROOT, normalize_css_files


def main() -> int:
    total = 0
    sites = 0
    for site in OUTROOT.iterdir():
        if not site.is_dir() or not (site / "assets").is_dir():
            continue
        hits = normalize_css_files(site, site.name)
        if hits:
            sites += 1
            total += hits
    print(f"重新剥离完成：{sites} 个站点，共 {total} 处绝对路径")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
