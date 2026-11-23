"""补跑：只重做报告里未达标（差异大/未解锁/截图失败）的页面，用修好的生成器（含 head 字体样式）。"""
import csv
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from batch_rebuild import (DATA, OUTROOT, REPO, SOURCES, Cdp, build_static, diff_ratio, normalize_css_files,
                           set_domain, wait_unlock)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
BAD = {"差异大", "未解锁", "截图失败"}


def load_targets():
    rows = list(csv.DictReader((OUTROOT / "report.csv").open(encoding="utf-8-sig")))
    targets = {}
    for row in rows:
        if row["状态"] in BAD:
            targets.setdefault(row["站点"], set()).add(row["路由"])
    return targets


def main() -> int:
    targets = load_targets()
    if os.environ.get("REPAIR_ONLY"):
        wanted = {s.strip() for s in os.environ["REPAIR_ONLY"].split(",") if s.strip()}
        targets = {k: v for k, v in targets.items() if k in wanted}
    if not targets:
        print("没有需要补跑的页面")
        return 0
    print("待补跑站点:", len(targets), "页面:", sum(len(v) for v in targets.values()), flush=True)

    out = OUTROOT / "report_repair.csv"
    new_file = not out.exists()
    fh = out.open("a", newline="", encoding="utf-8-sig")
    writer = csv.writer(fh)
    if new_file:
        writer.writerow(["站点", "路由", "页面", "原站高度(字符)", "静态页(字符)", "差异率%", "状态"])

    server = subprocess.Popen([sys.executable, "app.py", "--host", "127.0.0.1", "--port", "80"],
                              cwd=str(REPO), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              env={**__import__("os").environ, "GATEWAY_DATA_DIR": str(DATA)})
    time.sleep(3)
    try:
        for index, (kit, routes) in enumerate(sorted(targets.items()), 1):
            kit_dir = OUTROOT / kit
            css = [p.name for p in (kit_dir / "assets").iterdir() if p.suffix == ".css"] \
                if (kit_dir / "assets").is_dir() else []
            if not css:
                continue
            css_name = css[0]
            normalize_css_files(kit_dir, kit)
            set_domain(kit)
            cdp = Cdp(23000 + index % 300)
            shooter = None
            try:
                cdp.send("Runtime.enable")
                cdp.send("Page.enable")
                cdp.send("Emulation.setUserAgentOverride", userAgent=UA, acceptLanguage="ja-JP")
                cdp.send("Page.navigate", url="http://test.local/")
                unlocked = wait_unlock(cdp, 60)
                if not isinstance(unlocked, int) or unlocked <= 200:
                    for route in sorted(routes):
                        writer.writerow([kit, route, "-", unlocked, 0, "-", "仍未解锁"])
                    fh.flush()
                    print(f"  {kit}: 仍未解锁", flush=True)
                    continue
                shooter = Cdp(23500 + index % 300)
                shooter.send("Runtime.enable")
                shooter.send("Page.enable")
                for route in sorted(routes):
                    if route in ("/",):
                        nav_expr_route = "/"
                    else:
                        nav_expr_route = route
                    nav = cdp.ev("(async()=>{const el=document.querySelector('#app');"
                                 "const a=el&&el.__vue_app__;const r=a.config.globalProperties.$router;"
                                 f"await r.push('{nav_expr_route}');await new Promise(x=>setTimeout(x,1800));"
                                 "return JSON.stringify({cls:document.body.className,"
                                 "t:document.title,l:document.documentElement.lang})})()", 30)
                    try:
                        info = json.loads(nav or "{}")
                    except ValueError:
                        info = {}
                    html = cdp.ev("""(()=>{const root=document.querySelector('#app');
                      if(!root) return '';
                      root.querySelectorAll('*').forEach(el=>{
                        const cs=getComputedStyle(el);
                        if(cs.display==='none'||cs.visibility==='hidden'||cs.opacity==='0'){
                          el.setAttribute('data-gw-hidden','1');
                        }
                      });
                      return root.innerHTML;})()""", 30) or ""
                    root_fs = cdp.ev("getComputedStyle(document.documentElement).fontSize", 10) or ""
                    head_css = cdp.ev("Array.from(document.querySelectorAll('style'))"
                                      ".map(s=>s.textContent).join('\\n')", 20) or ""
                    safe = route.strip("/").replace("/", "_") or "login"
                    orig = OUTROOT / kit / "shots" / f"{safe}-orig.png"
                    # 先滚到底触发懒加载，再回顶部截图，避免原站截图里图片还没加载
                    cdp.ev("window.scrollTo(0, document.body.scrollHeight)", 8)
                    time.sleep(0.8)
                    cdp.ev("window.scrollTo(0,0)", 8)
                    time.sleep(0.4)
                    cdp.ev("document.activeElement&&document.activeElement.blur();window.scrollTo(0,0)", 8)
                    time.sleep(0.3)
                    cdp.shot(orig)
                    if len(html) < 300:
                        writer.writerow([kit, route, "-", len(html), 0, "-", "补跑:空页面"])
                        fh.flush()
                        continue
                    layout = cdp.ev("""JSON.stringify((()=>{const b=getComputedStyle(document.body);
                      const a=document.querySelector('#app'); const ac=a?getComputedStyle(a):null;
                      return {bh:b.height,bo:b.overflow,bov:b.overflowY,
                              ah:ac?ac.height:null,ao:ac?ac.overflow:null};})())""", 12) or "{}"
                    try:
                        lay = json.loads(layout)
                    except ValueError:
                        lay = {}
                    clip = ""
                    if lay.get("bo", "").startswith("hidden") or lay.get("bov") == "hidden":
                        body_h = lay.get("bh") or ""
                        if body_h and body_h not in ("auto", "0px"):
                            clip = (f"<style>body{{overflow:hidden;height:{body_h}}}"
                                    "#app{overflow:hidden;height:100%}</style>")
                    page = build_static(kit_dir, css_name, route, html, info.get("cls", ""),
                                        info.get("t", ""), info.get("l", "ja"),
                                        "<style>[data-gw-hidden]{display:none !important}</style>" + head_css + clip,
                                        root_fs)
                    ours = OUTROOT / kit / "shots" / f"{safe}-ours.png"
                    shooter.send("Page.navigate", url=page.as_uri())
                    time.sleep(1.5)
                    shooter.ev("window.scrollTo(0,0)", 8)
                    time.sleep(0.4)
                    shooter.ev("window.scrollTo(0,0)", 8)
                    shooter.shot(ours)
                    ratio = diff_ratio(orig, ours) if ours.exists() else -1
                    status = "OK" if 0 <= ratio < 0.5 else ("差异大" if ratio > 0 else "截图失败")
                    writer.writerow([kit, route, "-", len(html), len(html), f"{ratio:.3f}", "补跑:" + status])
                    fh.flush()
                    print(f"  {kit:26} {route:22} {ratio:.3f}% {status}", flush=True)
            finally:
                cdp.close()
                if shooter:
                    shooter.close()
    finally:
        fh.close()
        server.kill()
    print("补跑完成", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
