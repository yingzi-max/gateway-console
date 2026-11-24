import json, subprocess, time, urllib.request, pathlib
import websocket
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
def sections(url, port):
    p = subprocess.Popen([CHROME,"--headless=new","--disable-gpu","--no-sandbox","--no-first-run",
        f"--remote-debugging-port={port}", f"--user-data-dir=D:\\_shot\\s-{port}-{int(time.time()*1000)}",
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
    send("Page.enable"); send("Runtime.enable"); send("Page.navigate", url=url); time.sleep(8)
    expr = """JSON.stringify(Array.from(document.querySelectorAll('#app > *')).map(el=>{
      const r=el.getBoundingClientRect();
      return {tag:el.tagName, cls:(el.className||'').toString().slice(0,28),
              h:Math.round(r.height), y:Math.round(r.top), txt:(el.innerText||'').slice(0,30).replace(/\\n/g,' ')};
    }))"""
    rid = send("Runtime.evaluate", expression=expr, returnByValue=True)
    val=None; end=time.time()+15
    while time.time()<end:
        try: e=json.loads(ws.recv())
        except Exception: break
        if e.get("id")==rid: val=(e.get("result") or {}).get("result",{}).get("value"); break
    ws.close(); p.kill(); return json.loads(val or "[]")
orig = sections("http://test.local/", 9420)
ours = sections(pathlib.Path(r"D:\_rebuild_sites\jp_jaccs\login.html").as_uri(), 9421)
print("原站区块:", [(o["tag"], o["h"], o["txt"][:14]) for o in orig])
print("自建区块:", [(o["tag"], o["h"], o["txt"][:14]) for o in ours])
