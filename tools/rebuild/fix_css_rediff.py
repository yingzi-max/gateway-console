"""修复已生成站点的 CSS 绝对路径，并重新截图比对（不需要 console，纯离线）。"""
import argparse
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from batch_rebuild import OUTROOT, Cdp, diff_ratio

HTML_RE = re.compile(r'<div id="app">(.*)</div></body>', re.S)


def normalize_css(path: pathlib.Path, kit: str) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    before = text.count("/sites/")
    if before == 0:
        return 0
    text = text.replace(f"/sites/{kit}/assets/", "")
    text = text.replace(f"/sites/{kit}/", "")
    path.write_text(text, encoding="utf-8")
    return before


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sites", default="")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    sites = sorted(p for p in OUTROOT.iterdir() if p.is_dir() and (p / "assets").is_dir())
    if args.sites:
        wanted = {s.strip() for s in args.sites.split(",") if s.strip()}
        sites = [s for s in sites if s.name in wanted]
    if args.limit:
        sites = sites[:args.limit]

    shooter = Cdp(25000)
    shooter.send("Runtime.enable")
    shooter.send("Page.enable")
    rows = []
    try:
        for site in sites:
            fixed = sum(normalize_css(p, site.name) for p in (site / "assets").glob("*.css"))
            pages = sorted((site / "shots").glob("*-orig.png"))
            for orig in pages:
                safe = orig.name[:-len("-orig.png")]
                page = site / f"{safe}.html"
                if not page.is_file():
                    continue
                ours = site / "shots" / f"{safe}-ours.png"
                shooter.send("Page.navigate", url=page.as_uri())
                time.sleep(1.5)
                state = shooter.ev("JSON.stringify({r:document.readyState,"
                                   "img:Array.from(document.images).filter(i=>!i.complete).length})", 8)
                for _ in range(10):
                    try:
                        info = json.loads(state or "{}")
                    except ValueError:
                        info = {}
                    if info.get("r") == "complete" and info.get("img") == 0:
                        break
                    time.sleep(0.2)
                    state = shooter.ev("JSON.stringify({r:document.readyState,"
                                       "img:Array.from(document.images).filter(i=>!i.complete).length})", 8)
                shooter.shot(ours)
                ratio = diff_ratio(orig, ours) if ours.exists() else -1
                status = "OK" if 0 <= ratio < 0.5 else ("差异大" if ratio > 0 else "截图失败")
                rows.append([site.name, safe, f"{ratio:.3f}", status])
                print(f"  {site.name:28} {safe:22} {ratio:.3f}% {status}", flush=True)
            print(f"[{site.name}] CSS 替换 {fixed} 处绝对路径", flush=True)
    finally:
        shooter.close()

    report = OUTROOT / "report_cssfix.csv"
    with report.open("w", newline="", encoding="utf-8-sig") as fh:
        import csv
        writer = csv.writer(fh)
        writer.writerow(["站点", "页面", "差异率%", "状态"])
        writer.writerows(rows)
    ok = sum(1 for r in rows if r[3] == "OK")
    print(f"\n合计 {len(rows)} 页，OK {ok}，未达标 {len(rows) - ok}；明细 {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
