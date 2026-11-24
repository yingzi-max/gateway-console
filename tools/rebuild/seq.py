import json, subprocess, time, urllib.request, pathlib
import websocket
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
JS = """JSON.stringify((()=>{const out=[];document.querySelectorAll('h1,h2,h3,dl,dd,p'),0})())"""
def seq(url, port):
    p = subprocess.Popen([CHROME,"--headless=new","--disable-gpu","--no-sandbox","--no-first-run",
        f"--remote-debugging-port={port}", f"--user-data-dir=D:\\_shot\\sq-{port}-{int(time.time()*1000)}",
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
    expr = """JSON.stringify(Array.from(document.querySelectorAll('h1,h2,h3,dd')).map(el=>{
        const r=el.getBoundingClientRect();
        return [Math.round(r.top+window.scrollY), Math.round(r.height), (el.innerText||'').slice(0,14).replace(/\\n/g,' ')];
      }).filter(x=>x[1]>5))"""
    rid = send("Runtime.evaluate", expression=expr, returnByValue=True)
    val=None; end=time.time()+15
    while time.time()<end:
        try: e=json.loads(ws.recv())
        except Exception: break
        if e.get("id")==rid: val=(e.get("result") or {}).get("result",{}).get("value"); break
    ws.close(); p.kill(); return json.loads(val or "[]")
a = seq("http://test.local/", 9520)
b = seq(pathlib.Path(r"D:\_rebuild_sites\jp_jaccs\login.html").as_uri(), 9521)
print("原站条目:", len(a), " 自建条目:", len(b))
for i in range(max(len(a), len(b))):
    x = a[i] if i < len(a) else None
    y = b[i] if i < len(b) else None
    mark = ""
    if x and y and abs(x[0]-y[0]) > 3: mark = " <<<"
    if x and y and x[2][:8] != y[2][:8]: mark += " (文本不同)"
    if x or y:
        print(f"{str(x):>44} | {str(y):<44}{mark}")
