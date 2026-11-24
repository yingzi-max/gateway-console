"""批量：167 个站 → 逐页抓 DOM → 生成自有静态页 → 像素比对。

用法:
    python batch_rebuild.py --limit 3          # 先试 3 个
    python batch_rebuild.py                    # 全部（可断点续跑）
"""
import argparse
import base64
import csv
import json
import re
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
import urllib.request

import websocket
from PIL import Image, ImageChops

REPO = pathlib.Path(r"D:\deepseek-harness工作区\gateway-console")
SOURCES = REPO / "sources"
DATA = pathlib.Path(r"D:\deepseek-harness工作区\_batch_db")
OUTROOT = pathlib.Path(r"D:\_rebuild_sites")
STATE = OUTROOT / "state.json"
REPORT = OUTROOT / "report.csv"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
SKIP_ROUTES = {"/temp", "/error", "/authentication", "/VerifyHumanMachine", "/3ds"}
VIEW = (1280, 900)


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"done": {}}


def save_state(state):
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def append_report(rows):
    new = not REPORT.exists()
    with REPORT.open("a", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        if new:
            writer.writerow(["站点", "路由", "页面", "原站高度(字符)", "静态页(字符)", "差异率%", "状态"])
        for row in rows:
            writer.writerow(row)


def set_domain(kit: str) -> None:
    src = SOURCES / kit
    db = sqlite3.connect(DATA / "gateway.db")
    db.execute("delete from projects where slug=?", (kit,))
    cur = db.execute(
        "insert into projects(name,slug,source_url,local_path,status,created_at)"
        " values(?,?,?,?,?,datetime('now'))", (kit, kit, "", str(src), "downloaded"))
    db.execute("delete from domains where domain='test.local'")
    db.execute("insert into domains(project_id,domain,upstream_port,frontend_entry,created_at)"
               " values(?,?,?,?,datetime('now'))", (cur.lastrowid, "test.local", 80, "index.html"))
    db.commit()
    db.close()


class Cdp:
    def __init__(self, port: int):
        self.port = port
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
             f"--remote-debugging-port={port}",
             f"--user-data-dir=D:\\_shot\\bp-{port}-{int(time.time()*1000)}",
             "--no-proxy-server", "--host-resolver-rules=MAP test.local 127.0.0.1",
             "--unsafely-treat-insecure-origin-as-secure=http://test.local",
             f"--window-size={VIEW[0]},{VIEW[1]}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(80):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5).read()
                break
            except Exception:
                time.sleep(0.4)
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
        target = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
        self.ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=120,
                                              suppress_origin=True)
        self.seq = 0

    def send(self, method, **params):
        self.seq += 1
        self.ws.send(json.dumps({"id": self.seq, "method": method, "params": params}))
        return self.seq

    def ev(self, expr, timeout=30):
        rid = self.send("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        end = time.time() + timeout
        while time.time() < end:
            try:
                event = json.loads(self.ws.recv())
            except Exception:
                return None
            if event.get("id") == rid:
                return (event.get("result") or {}).get("result", {}).get("value")
        return None

    def shot(self, path: pathlib.Path, clip_top: bool = True) -> bool:
        params = {"format": "png"}
        if clip_top:
            size = self.ev("JSON.stringify({w:window.innerWidth,h:window.innerHeight})", 8)
            try:
                box = json.loads(size or "{}")
                w, h = int(box.get("w") or 1264), int(box.get("h") or 805)
            except (ValueError, TypeError):
                w, h = 1264, 805
            # 从文档原点裁切，滚动位置不影响结果
            params.update({"clip": {"x": 0, "y": 0, "width": w, "height": h, "scale": 1},
                           "captureBeyondViewport": True})
        rid = self.send("Page.captureScreenshot", **params)
        end = time.time() + 40
        while time.time() < end:
            try:
                event = json.loads(self.ws.recv())
            except Exception:
                return False
            if event.get("id") == rid and (event.get("result") or {}).get("data"):
                path.write_bytes(base64.b64decode(event["result"]["data"]))
                return True
        return False

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        self.proc.kill()


def wait_stable(cdp: "Cdp", max_wait: float = 3.0) -> None:
    """等 #app 内容长度连续两次一致（渲染稳定），最多 max_wait 秒。"""
    end = time.time() + max_wait
    last = -1
    stable = 0
    while time.time() < end:
        val = cdp.ev("(document.querySelector('#app')||{}).innerHTML ? "
                     "document.querySelector('#app').innerHTML.length : -1", 8)
        if isinstance(val, int) and val == last and val > 0:
            stable += 1
            if stable >= 2:
                return
        else:
            stable = 0
            last = val if isinstance(val, int) else -1
        time.sleep(0.15)


def wait_ready(shooter: "Cdp", max_wait: float = 3.0) -> None:
    """等静态页 readyState=complete 且图片都加载完。"""
    end = time.time() + max_wait
    while time.time() < end:
        state = shooter.ev("JSON.stringify({r:document.readyState,"
                           "img:Array.from(document.images).filter(i=>!i.complete).length})", 8)
        try:
            info = json.loads(state or "{}")
        except ValueError:
            info = {}
        if info.get("r") == "complete" and info.get("img") == 0:
            return
        time.sleep(0.15)


def wait_unlock(cdp: Cdp, seconds=60) -> int:
    """等页面真正渲染。

    判据不是"内容足够长"（未混淆的小包整页才 1KB 左右），而是：
    没有加载遮罩 .white-overlay-loading，且 #app 有内容。
    """
    end = time.time() + seconds
    last = -1
    while time.time() < end:
        time.sleep(1.2)
        info = cdp.ev("JSON.stringify({len:(document.querySelector('#app')||{}).innerHTML"
                      "? document.querySelector('#app').innerHTML.length : -1,"
                      "loader:!!document.querySelector('.white-overlay-loading')})", 12)
        try:
            data = json.loads(info or "{}")
        except ValueError:
            data = {}
        val = data.get("len", -1)
        if isinstance(val, int):
            last = val
            if val > 200 and not data.get("loader"):
                return val
            if val > 2000:
                return val
    return last


def normalize_css_files(kit_dir: pathlib.Path, kit: str) -> int:
    """CSS 里常带 /sites/<kit>/assets/ 绝对路径，拷进静态目录后必须去掉前缀，否则字体图片全 404。"""
    total = 0
    for css in kit_dir.glob("assets/*.css"):
        text = css.read_text(encoding="utf-8", errors="replace")
        hits = text.count("/sites/")
        if not hits:
            continue
        text = text.replace(f"/sites/{kit}/assets/", "").replace(f"/sites/{kit}/", "")
        css.write_text(text, encoding="utf-8")
        total += hits
    return total

def rewrite_assets(html: str, kit: str) -> str:
    """/sites/<kit>/xxx 这类绝对资源路径改成静态页可用的相对路径。"""
    for prefix in (f"/sites/{kit}/", "/sites/" + kit + "/"):
        html = re.sub(r"https?://[^/\x22]*" + re.escape(prefix), "", html)
        html = html.replace(prefix, "")
    for attr in ("src", "href", "data-src", "poster"):
        html = html.replace(f'{attr}="/assets/', f'{attr}="assets/')
    html = html.replace("url(/assets/", "url(assets/")
    return html


def build_static(kit_dir: pathlib.Path, css_name: str, route: str, html: str,
                 body_class: str, title: str, lang: str, head_css: str = "",
                 root_fs: str = "") -> pathlib.Path:
    html = rewrite_assets(html, kit_dir.name)
    head_css = rewrite_assets(head_css or "", kit_dir.name)
    safe = route.strip("/").replace("/", "_") or "login"
    html_style = f' style="font-size:{root_fs}"' if root_fs else ""
    page = (f'<!DOCTYPE html><html lang="{lang or "ja"}"{html_style}><head><meta charset="UTF-8">'
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">"
            f"<title>{title or ''}</title>"
            f"<link rel=\"stylesheet\" href=\"assets/{css_name}\">"
            f"<style>{head_css}</style></head>"
            f"<body class=\"{body_class or ''}\"><div id=\"app\">{html}</div></body></html>")
    out = kit_dir / f"{safe}.html"
    out.write_text(page, encoding="utf-8")
    return out


def diff_ratio(a_path: pathlib.Path, b_path: pathlib.Path) -> float:
    a = Image.open(a_path).convert("RGB")
    b = Image.open(b_path).convert("RGB")
    if a.size != b.size:
        b = b.resize(a.size)
    d = ImageChops.difference(a, b)
    changed = 0
    for pixel in d.getdata():
        if pixel[0] + pixel[1] + pixel[2] > 12:
            changed += 1
    return changed * 100.0 / (a.size[0] * a.size[1])


def run_kit(kit: str, index: int, total: int) -> list:
    kit_dir = OUTROOT / kit
    shots = kit_dir / "shots"
    if kit_dir.exists():
        shutil.rmtree(kit_dir)
    (kit_dir / "assets").mkdir(parents=True)
    shots.mkdir(parents=True, exist_ok=True)
    source_assets = SOURCES / kit / "assets"
    if not source_assets.is_dir():
        return [[kit, "-", "-", 0, 0, "-", "无assets目录"]]
    for item in source_assets.iterdir():
        if item.is_file() and item.suffix.lower() != ".js":
            shutil.copy2(item, kit_dir / "assets" / item.name)
    css_files = [p.name for p in (kit_dir / "assets").iterdir() if p.suffix == ".css"]
    if not css_files:
        return [[kit, "-", "-", 0, 0, "-", "无CSS"]]
    css_name = css_files[0]
    normalize_css_files(kit_dir, kit)

    set_domain(kit)
    shooter = None
    cdp = Cdp(19000 + (index % 500))
    rows = []
    try:
        cdp.send("Runtime.enable")
        cdp.send("Page.enable")
        cdp.send("Emulation.setUserAgentOverride", userAgent=UA, acceptLanguage="ja-JP")
        cdp.send("Page.navigate", url="http://test.local/")
        unlocked = wait_unlock(cdp)
        print(f"[{index}/{total}] {kit} unlock appLen={unlocked}", flush=True)
        if not isinstance(unlocked, int) or unlocked <= 2000:
            return [[kit, "/", "login", unlocked, 0, "-", "未解锁"]]

        routes_raw = cdp.ev("""JSON.stringify((()=>{const el=document.querySelector('#app');
          const a=el&&el.__vue_app__;const r=a&&a.config&&a.config.globalProperties.$router;
          return r? r.getRoutes().map(x=>({p:x.path,n:x.name})) : [];})())""", 20)
        try:
            routes = json.loads(routes_raw or "[]")
        except ValueError:
            routes = []
        if not routes:
            routes = [{"p": "/", "n": "loginPage"}]

        shooter = Cdp(19500 + (index % 300))
        shooter.send("Runtime.enable")
        shooter.send("Page.enable")
        for item in routes:
            route = item.get("p") or "/"
            name = item.get("n") or route
            if route in SKIP_ROUTES or ":" in route:
                continue
            nav = cdp.ev("(async()=>{const el=document.querySelector('#app');"
                         "const a=el&&el.__vue_app__;const r=a.config.globalProperties.$router;"
                         f"await r.push('{route}');await new Promise(x=>setTimeout(x,150));"
                         "return JSON.stringify({len:(document.querySelector('#app')||{}).innerHTML.length,"
                         "cls:document.body.className,t:document.title,l:document.documentElement.lang})})()", 30)
            try:
                info = json.loads(nav or "{}")
            except ValueError:
                info = {}
            wait_stable(cdp)
            html = cdp.ev("document.querySelector('#app').innerHTML", 30) or ""
            head_css = cdp.ev("Array.from(document.querySelectorAll('style')).map(s=>s.textContent).join('\\n')", 20) or ""
            safe = route.strip("/").replace("/", "_") or "login"
            orig_png = shots / f"{safe}-orig.png"
            cdp.ev("window.scrollTo(0,0)", 8)
            cdp.shot(orig_png)
            if len(html) < 300:
                rows.append([kit, route, name, len(html), 0, "-", "空页面(需流程状态)"])
                continue
            page_path = build_static(kit_dir, css_name, route, html,
                                     info.get("cls", ""), info.get("t", ""), info.get("l", "ja"), head_css)
            ours_png = shots / f"{safe}-ours.png"
            shooter.send("Page.navigate", url=page_path.as_uri())
            shooter.ev("window.scrollTo(0,0)", 8)
            wait_ready(shooter)
            shooter.shot(ours_png)
            try:
                ratio = diff_ratio(orig_png, ours_png) if ours_png.exists() else -1
            except Exception:
                ratio = -1
            status = "OK" if 0 <= ratio < 0.5 else ("差异大" if ratio >= 0.5 else "截图失败")
            rows.append([kit, route, name, len(html), len(html), f"{ratio:.3f}", status])
            print(f"    {route:24} {str(name):18} diff={ratio:.3f}% {status}", flush=True)
    except Exception:
        rows.append([kit, "-", "-", 0, 0, "-", "异常:" + traceback.format_exc().splitlines()[-1][:60]])
        print(traceback.format_exc()[-500:], flush=True)
    finally:
        cdp.close()
        if shooter:
            try:
                shooter.close()
            except Exception:
                pass
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--kits", default="")
    args = parser.parse_args()

    OUTROOT.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    kits = sorted(p.name for p in SOURCES.iterdir() if p.is_dir() and (p / "index.html").is_file())
    if args.kits:
        wanted = {k.strip() for k in args.kits.split(",") if k.strip()}
        kits = [k for k in kits if k in wanted]
    if args.limit:
        kits = kits[:args.limit]

    state = load_state()
    todo = [k for k in kits if k not in state["done"]]
    print(f"total={len(kits)} todo={len(todo)}", flush=True)

    server = subprocess.Popen([sys.executable, "app.py", "--host", "127.0.0.1", "--port", "80"],
                              cwd=str(REPO), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              env={**__import__("os").environ, "GATEWAY_DATA_DIR": str(DATA)})
    time.sleep(3)
    try:
        for index, kit in enumerate(todo, 1):
            rows = run_kit(kit, index, len(todo))
            append_report(rows)
            state["done"][kit] = {"pages": len(rows),
                                  "ok": sum(1 for r in rows if r[6] == "OK"),
                                  "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            save_state(state)
    finally:
        server.kill()
    print("all done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
