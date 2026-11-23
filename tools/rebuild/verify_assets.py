"""校验静态站点的 assets 与源包是否一致（按大小），不一致就重拷。"""
import pathlib
import shutil

ROOT = pathlib.Path(r"D:\_rebuild_sites")
SOURCES = pathlib.Path(r"D:\deepseek-harness工作区\gateway-console\sources")


def main() -> int:
    fixed_sites = {}
    checked = 0
    for site in ROOT.iterdir():
        if not site.is_dir():
            continue
        src = SOURCES / site.name / "assets"
        dst = site / "assets"
        if not src.is_dir() or not dst.is_dir():
            continue
        bad = []
        for local in dst.iterdir():
            if not local.is_file():
                continue
            origin = src / local.name
            if not origin.is_file():
                continue
            checked += 1
            if local.stat().st_size != origin.stat().st_size:
                bad.append((local.name, local.stat().st_size, origin.stat().st_size,
                            local.read_bytes()[:16].count(0)))
        if bad:
            fixed_sites[site.name] = bad
            shutil.rmtree(dst)
            shutil.copytree(src, dst)
    total_bad = sum(len(v) for v in fixed_sites.values())
    print(f"检查文件 {checked} 个；不一致站点 {len(fixed_sites)} 个，文件 {total_bad} 个（已重拷）")
    for name, items in list(fixed_sites.items())[:10]:
        print(f"  {name}: {len(items)} 个，例: {items[0][0]} 本地{items[0][1]}B vs 源{items[0][2]}B 前导零{items[0][3]}")
    if fixed_sites:
        (ROOT / "fixed_sites.txt").write_text("\n".join(fixed_sites), encoding="utf-8")
        print("受影响站点已写入 fixed_sites.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
