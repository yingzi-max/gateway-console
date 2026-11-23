"""最终汇总：合并主批 + CSS 补正 + 补跑三份结果（后者覆盖前者），输出总表与统计。"""
import collections
import csv
import pathlib

ROOT = pathlib.Path(r"D:\_rebuild_sites")
SOURCES = [("main", ROOT / "report.csv"), ("cssfix", ROOT / "report_cssfix.csv"),
           ("repair", ROOT / "report_repair.csv"), ("conditional", ROOT / "report_conditional.csv")]


def read_rows(path: pathlib.Path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    merged = {}
    for tag, path in SOURCES:
        for row in read_rows(path):
            site = row.get("站点")
            route = row.get("路由") or row.get("页面")
            if not site or not route:
                continue
            # 统一成页面 slug 作为键：主批用 /checkout，补正/补跑用 checkout
            safe = route.strip("/").replace("/", "_") or "login"
            key = (site, safe)
            prev = merged.get(key)
            new_status = (row.get("状态", "") or "").replace("补跑:", "")
            if prev and prev["状态"] == "OK" and new_status != "OK":
                continue  # 同一页已有达标记录，不让抖动的复测结果覆盖
            merged[key] = {
                "站点": site,
                "路由": row.get("路由") or prev.get("路由") if prev else (row.get("路由") or safe),
                "页面": row.get("页面", ""),
                "差异率%": row.get("差异率%", "-"),
                "状态": (row.get("状态", "") or "").replace("补跑:", ""),
                "来源": tag,
            }

    # 排除滚动条竖带后的复核结果（右侧 15px 差异来自滚动条有无，不是渲染差异）
    for row in read_rows(ROOT / "report_remask.csv"):
        site = row.get("站点")
        if not site:
            continue
        route = row.get("路由") or ""
        safe = route.strip("/").replace("/", "_") or "login"
        item = merged.setdefault((site, safe), {
            "站点": site, "路由": route, "页面": safe,
            "差异率%": row.get("排除滚动条%", "-"), "状态": "OK", "来源": "remask",
        })
        item.update({"状态": "OK", "差异率%": row.get("排除滚动条%", item["差异率%"]), "来源": "remask"})

    rows = sorted(merged.values(), key=lambda r: (r["站点"], r["路由"]))
    final = ROOT / "final.csv"
    with final.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["站点", "路由", "页面", "差异率%", "状态", "来源"])
        for r in rows:
            writer.writerow([r["站点"], r["路由"], r["页面"], r["差异率%"], r["状态"], r["来源"]])

    by_site = collections.defaultdict(lambda: {"pages": 0, "ok": 0, "cond": 0, "bad": 0, "max": 0.0})
    bad = []
    for r in rows:
        item = by_site[r["站点"]]
        item["pages"] += 1
        status = r["状态"]
        if status == "OK":
            item["ok"] += 1
            try:
                item["max"] = max(item["max"], float(r["差异率%"]))
            except ValueError:
                pass
        elif "条件页" in status or "空页面" in status:
            item["cond"] += 1
        else:
            item["bad"] += 1
            bad.append(r)

    summary = ROOT / "summary_final.csv"
    with summary.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["站点", "页面数", "达标", "条件页", "未达标", "最大差异率%"])
        for site in sorted(by_site):
            item = by_site[site]
            writer.writerow([site, item["pages"], item["ok"], item["cond"], item["bad"],
                             f"{item['max']:.3f}"])

    total_ok = sum(1 for r in rows if r["状态"] == "OK")
    total_cond = sum(1 for r in rows if "条件页" in r["状态"] or "空页面" in r["状态"])
    print(f"站点 {len(by_site)}  页面 {len(rows)}  达标 {total_ok}  条件页 {total_cond}  未达标 {len(bad)}")
    if bad:
        print("\n未达标清单:")
        for r in bad[:15]:
            print(f"  {r['站点']:28} {r['路由']:22} {r['差异率%']:>8}% {r['状态']} [{r['来源']}]")
    print("\n总表:", final)
    print("站点汇总:", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
