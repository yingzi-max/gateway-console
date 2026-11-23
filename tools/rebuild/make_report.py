"""汇总报告：按站点统计验收结果，列出未达标页面。"""
import collections
import csv
import pathlib

ROOT = pathlib.Path(r"D:\_rebuild_sites")
REPORT = ROOT / "report.csv"
SUMMARY = ROOT / "summary.csv"


def main() -> int:
    rows = list(csv.DictReader(REPORT.open(encoding="utf-8-sig")))
    if not rows:
        print("报告为空")
        return 1

    by_site = collections.defaultdict(lambda: {"pages": 0, "ok": 0, "cond": 0, "bad": 0, "max": 0.0})
    bad_rows = []
    for row in rows:
        site = row["站点"]
        item = by_site[site]
        item["pages"] += 1
        status = row["状态"]
        ratio = row["差异率%"]
        if status == "OK":
            item["ok"] += 1
            if ratio not in ("-", ""):
                item["max"] = max(item["max"], float(ratio))
        elif "条件页" in status or "空页面" in status:
            item["cond"] += 1
        else:
            item["bad"] += 1
            bad_rows.append(row)

    with SUMMARY.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["站点", "页面数", "达标", "条件页", "未达标", "最大差异率%"])
        for site in sorted(by_site):
            item = by_site[site]
            writer.writerow([site, item["pages"], item["ok"], item["cond"], item["bad"],
                             f"{item['max']:.3f}"])

    total_pages = len(rows)
    total_ok = sum(1 for r in rows if r["状态"] == "OK")
    total_cond = sum(1 for r in rows if "条件页" in r["状态"] or "空页面" in r["状态"])
    print(f"站点数 {len(by_site)}  页面记录 {total_pages}  达标 {total_ok}  条件页 {total_cond}  未达标 {len(bad_rows)}")
    if bad_rows:
        print("\n未达标页面（差异 >= 0.5% 或异常）:")
        for row in bad_rows[:20]:
            print(f"  {row['站点']:26} {row['路由']:22} {row['差异率%']:>8}% {row['状态']}")
    worst = sorted((float(r["差异率%"]) for r in rows if r["差异率%"] not in ("-", "")), reverse=True)[:5]
    print("\n最大差异率 top5:", worst)
    print("明细:", SUMMARY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
