import base64, json, subprocess, time, urllib.request, pathlib
import websocket
from PIL import Image, ImageChops
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
site = pathlib.Path(r"D:\_rebuild_sites\jp_jaccs")
orig = Image.open(site/"shots"/"login-orig.png").convert("RGB")
src = (site/"login.html").read_text(encoding="utf-8")
print("原始 html 头:", src[:90].replace("\n"," "))
def shoot(html_path, port, out):
    p = subprocess.Popen([CHROME,"--headless=new","--disable-gpu","--no-sandbox","--no-first-run",
        f"--remote-debugging-port={port}", f"--user-data-dir=D:\\_shot\\lgb-{port}-{int(time.time()*1000)}",
        "--no-proxy-server","--window-size=1280,900","about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(80):
        try: urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5).read(); break
        except Exception: time.sleep(0.4)
    req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
    t = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=60, suppress_origin=True)
    s=[0]
    def send(m, **kw):
        s[0]+=1; ws.send(json.dumps({"id":s[0],"method":m,"params":kw})); return s[0]
    send("Page.enable"); send("Page.navigate", url=html_path.as_uri()); time.sleep(2)
    rid = send("Page.captureScreenshot", format="png")
    end=time.time()+30
    while time.time()<end:
        try: e=json.loads(ws.recv())
        except Exception: break
        if e.get("id")==rid and (e.get("result") or {}).get("data"):
            out.write_bytes(base64.b64decode(e["result"]["data"])); break
    ws.close(); p.kill()
for i, (tag, html) in enumerate([("base", src), ("en", src.replace('<html lang="ja"', '<html lang="en"', 1))]):
    tmp = site/f"_lgb_{tag}.html"; tmp.write_text(html, encoding="utf-8")
    out = site/"shots"/f"_lgb_{tag}.png"
    shoot(tmp, 9550+i, out)
    b = Image.open(out).convert("RGB")
    if b.size != orig.size: b = b.resize(orig.size)
    d = ImageChops.difference(orig,b)
    ch = sum(1 for px in d.getdata() if sum(px) > 12)
    print(f"{tag}: {ch*100/(orig.size[0]*orig.size[1]):.3f}%")
