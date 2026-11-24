"""条件页补抓：/VerifyHumanMachine、/authentication、/3ds。

这些页面要么需要流程状态、要么需要站点配置才渲染。这里在页面里注入对应状态再抓：
- 机器人页：注入 robot_detection_content 后跳转
- 自定义验证页：注入 siteConfig（custom_verification）
- 3DS：尝试直接跳转，取不到就标记为条件页

用法: python conditional_pass.py [--limit N]
"""
import argparse
import json
import sqlite3
import subprocess
import sys
import time

from batch_rebuild import (DATA, OUTROOT, REPO, SOURCES, Cdp, append_report,
                           build_static, diff_ratio, load_state, wait_unlock)

PAGES = [
    ("/VerifyHumanMachine", "robotPage",
     "localStorage.setItem('robot_detection_content', 'セキュリティ確認のため、以下の認証を行ってください。');"),
    ("/authentication", "customPage",
     "localStorage.setItem('siteConfig', JSON.stringify({label:'本人確認', title:'本人確認のお願い', "
     "input_title1:'確認コード', btn_title:'送信', content:'本人確認のため、確認コードを入力してください。'}));"),
    ("/3ds", "3ds", ""),
]


def set_domain(kit: str) -> None:
    db = sqlite3.connect(DATA / "gateway.db")
    db.execute("delete from projects where slug=?", (kit,))
    cur = db.execute("insert into projects(name,slug,source_url,local_path,status,created_at)"
                     " values(?,?,?,?,?,datetime('now'))",
                     (kit, kit, "", str(SOURCES / kit), "downloaded"))
    db.execute("delete from domains where domain='test.local'")
    db.execute("insert into domains(project_id,domain,upstream_port,frontend_entry,created_at)"
               " values(?,?,?,?,datetime('now'))", (cur.lastrowid, "test.local", 80, "index.html"))
    db.commit()
    db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    state = load_state()
    kits = sorted(state["done"].keys())
    if args.limit:
        kits = kits[:args.limit]
    if not kits:
        print("主批还没跑完，先跑主批")
        return 0

    server = subprocess.Popen([sys.executable, "app.py", "--host", "127.0.0.1", "--port", "80"],
                              cwd=str(REPO), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              env={**__import__("os").environ, "GATEWAY_DATA_DIR": str(DATA)})
    time.sleep(3)
    rows = []
    try:
        for index, kit in enumerate(kits, 1):
            kit_dir = OUTROOT / kit
            if not (kit_dir / "assets").is_dir():
                continue
            css_files = [p.name for p in (kit_dir / "assets").iterdir() if p.suffix == ".css"]
            if not css_files:
                continue
            css_name = css_files[0]
            set_domain(kit)
            cdp = Cdp(20000 + (index % 400))
            try:
                cdp.send("Runtime.enable")
                cdp.send("Page.enable")
                cdp.send("Emulation.setUserAgentOverride",
                         userAgent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
                         acceptLanguage="ja-JP")
                cdp.send("Page.navigate", url="http://test.local/")
                if not (wait_unlock(cdp, 45) or 0) > 2000:
                    rows.append([kit, "-", "-", 0, 0, "-", "未解锁"])
                    continue
                for route, name, seed in PAGES:
                    if seed:
                        cdp.ev(seed + "'ok'", 15)
                    nav = cdp.ev("(async()=>{const el=document.querySelector('#app');"
                                 "const a=el&&el.__vue_app__;const r=a.config.globalProperties.$router;"
                                 f"await r.push('{route}');await new Promise(x=>setTimeout(x,2200));"
                                 "return JSON.stringify({len:(document.querySelector('#app')||{}).innerHTML.length,"
                                 "cls:document.body.className,t:document.title,l:document.documentElement.lang})})()", 30)
                    try:
                        info = json.loads(nav or "{}")
                    except ValueError:
                        info = {}
                    html = cdp.ev("document.querySelector('#app').innerHTML", 30) or ""
                    if len(html) < 300:
                        rows.append([kit, route, name, len(html), 0, "-", "条件页(无可渲染内容)"])
                        print(f"  {kit} {route} 空", flush=True)
                        continue
                    safe = route.strip("/").replace("/", "_")
                    orig_png = OUTROOT / kit / "shots" / f"{safe}-orig.png"
                    cdp.shot(orig_png)
                    page_path = build_static(kit_dir, css_name, route, html,
                                             info.get("cls", ""), info.get("t", ""), info.get("l", "ja"))
                    ours_png = OUTROOT / kit / "shots" / f"{safe}-ours.png"
                    shot = Cdp(20500 + (index % 400))
                    try:
                        shot.send("Runtime.enable")
                        shot.send("Page.enable")
                        shot.send("Page.navigate", url=page_path.as_uri())
                        time.sleep(2.5)
                        shot.shot(ours_png)
                    finally:
                        shot.close()
                    ratio = diff_ratio(orig_png, ours_png) if ours_png.exists() else -1
                    status = "OK" if 0 <= ratio < 0.5 else ("差异大" if ratio > 0 else "截图失败")
                    rows.append([kit, route, name, len(html), len(html), f"{ratio:.3f}", "条件页" + status])
                    print(f"  {kit} {route} diff={ratio:.3f}%", flush=True)
            finally:
                cdp.close()
    finally:
        server.kill()
    append_report(rows)
    print("条件页补抓完成:", len(rows), "条", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
