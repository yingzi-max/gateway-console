import json, subprocess, time, urllib.request
import websocket
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
P = 9410
proc = subprocess.Popen([CHROME,"--headless=new","--disable-gpu","--no-sandbox","--no-first-run",
  f"--remote-debugging-port={P}", f"--user-data-dir=D:\\_shot\\cl-{int(time.time()*1000)}",
  "--no-proxy-server","--host-resolver-rules=MAP test.local 127.0.0.1",
  "--unsafely-treat-insecure-origin-as-secure=http://test.local","--window-size=1280,900","about:blank"],
  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(80):
    try: urllib.request.urlopen(f"http://127.0.0.1:{P}/json/version", timeout=5).read(); break
    except Exception: time.sleep(0.4)
req = urllib.request.Request(f"http://127.0.0.1:{P}/json/new?about:blank", method="PUT")
t = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=60, suppress_origin=True)
seq=[0]
def send(m, **kw):
    seq[0]+=1; ws.send(json.dumps({"id":seq[0],"method":m,"params":kw})); return seq[0]
def ev(expr, tmo=20):
    rid=send("Runtime.evaluate", expression=expr, returnByValue=True)
    end=time.time()+tmo
    while time.time()<end:
        try: e=json.loads(ws.recv())
        except Exception: return None
        if e.get("id")==rid: return (e.get("result") or {}).get("result",{}).get("value")
    return None
send("Page.enable"); send("Runtime.enable")
send("Page.navigate", url="http://test.local/"); time.sleep(9)
expr = """JSON.stringify((()=>{
  const out=[];
  document.querySelectorAll('body,body *').forEach(el=>{
    const cs=getComputedStyle(el);
    if (el.scrollHeight - el.clientHeight > 100 && el.clientHeight>400) {
      out.push({tag:el.tagName, cls:(el.className||'').toString().slice(0,40),
                ch:el.clientHeight, sh:el.scrollHeight, of:cs.overflow, ofy:cs.overflowY,
                h:cs.height, mh:cs.maxHeight});
    }
  });
  out.sort((a,b)=>b.sh-a.sh);
  return {bodyH:getComputedStyle(document.body).height, bodyOf:getComputedStyle(document.body).overflow,
          htmlH:getComputedStyle(document.documentElement).height,
          docSH:document.documentElement.scrollHeight,
          top: out.slice(0,6)};
})())"""
print(ev(expr))
ws.close(); proc.kill()
