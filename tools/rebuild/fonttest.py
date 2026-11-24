import base64, json, subprocess, time, urllib.request, pathlib
import websocket
from PIL import Image, ImageChops
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
CSS = "html,body,*{font-family:Arial,'Noto Sans JP',sans-serif !important;line-height:1.35 !important}"

def shot(url, port, out):
    p = subprocess.Popen([CHROME,"--headless=new","--disable-gpu","--no-sandbox","--no-first-run",
        f"--remote-debugging-port={port}", f"--user-data-dir=D:\\_shot\\fx-{port}-{int(time.time()*1000)}",
        "--no-proxy-server","--host-resolver-rules=MAP test.local 127.0.0.1",
        "--unsafely-treat-insecure-origin-as-secure=http://test.local","--window-size=1280,900","about:blank"],
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
    send("Page.enable"); send("Runtime.enable")
    send("Emulation.setUserAgentOverride", userAgent=UA, acceptLanguage="ja-JP")
    send("Page.navigate", url=url); time.sleep(8)
    send("Runtime.evaluate", expression=f"(()=>{{const st=document.createElement('style');st.textContent={CSS!r};document.head.appendChild(st);return 1}})()")
    time.sleep(2)
    rid = send("Page.captureScreenshot", format="png")
    end=time.time()+30
    while time.time()<end:
        try: e=json.loads(ws.recv())
        except Exception: break
        if e.get("id")==rid and (e.get("result") or {}).get("data"):
            out.write_bytes(base64.b64decode(e["result"]["data"])); break
    ws.close(); p.kill()

base = pathlib.Path(r"D:\_shot\fonttest"); base.mkdir(parents=True, exist_ok=True)
shot("http://test.local/", 9480, base/"a.png")
shot(pathlib.Path(r"D:\_rebuild_sites\jp_jaccs\login.html").as_uri(), 9481, base/"b.png")
a = Image.open(base/"a.png").convert("RGB"); b = Image.open(base/"b.png").convert("RGB")
if a.size != b.size: b = b.resize(a.size)
d = ImageChops.difference(a,b)
ch = sum(1 for px in d.getdata() if sum(px) > 12)
print("强制同字体后差异率: %.3f%%" % (ch*100/(a.size[0]*a.size[1])), "bbox:", d.getbbox())
