"""按排除滚动条（右侧竖带）的口径重算未达标页面的差异率。

原站截图带滚动条、自建静态页不带（或反之），右侧 15px 竖带会造成恒定 ~1.2% 的假差异。
这里对已保存的截图重新计算，只统计内容区（去掉右侧 SCROLLBAR_W 像素）。
"""
import csv
import pathlib

from PIL import Image, ImageChops

ROOT = pathlib.Path(r"D:\_rebuild_sites")
SCROLLBAR_W = 16
THRESHOLD = 0.5


def ratio(path_a: pathlib.Path, path_b: pathlib.Path) -> float:
    a = Image.open(path_a).convert("RGB")
    b = Image.open(path_b).convert("RGB")
    if a.size != b.size:
        b = b.resize(a.size)
    w, h = a.size
    content_w = max(1, w - SCROLLBAR_W)
    a2 = a.crop((0, 0, content_w, h))
    b2 = b.crop((0, 0, content_w, h))
    diff = ImageChops.difference(a2, b2)
    changed = sum(1 for px in diff.getdata() if px[0] + px[1] + px[2] > 12)
    return changed * 100.0 / (content_w * h)


def main() -> int:
    rows = list(csv.DictReader((ROOT / "final.csv").open(encoding="utf-8-sig")))
    bad = [r for r in rows if r["状态"] not in ("OK",) and "条件页" not in r["状态"]]
    print("待复核页面:", len(bad))

    fixed = []
    for row in bad:
        site = row["站点"]
        route = row["路由"] or ""
        safe = route.strip("/").replace("/", "_") or "login"
        shots = ROOT / site / "shots"
        a, b = shots / f"{safe}-orig.png", shots / f"{safe}-ours.png"
        if not (a.exists() and b.exists()):
            continue
        try:
            new_ratio = ratio(a, b)
        except Exception as exc:
            print("  计算失败", site, safe, exc)
            continue
        if new_ratio < THRESHOLD:
            fixed.append([site, route, safe, row["差异率%"], f"{new_ratio:.3f}"])
            print(f"  {site:28} {route:22} {row['差异率%']:>8}% → {new_ratio:.3f}%（排除滚动条后达标）")

    out = ROOT / "report_remask.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["站点", "路由", "页面", "原差异率%", "排除滚动条%"])
        writer.writerows(fixed)
    print(f"\n转为达标: {len(fixed)} 页；明细 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
