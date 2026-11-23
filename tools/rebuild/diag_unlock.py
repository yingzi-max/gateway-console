"""Diagnose why a kit does not render: console errors, network failures, DOM state."""
import json
import subprocess
import sys
import time
import urllib.request

import websocket

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
EXTRA = ["--unsafely-treat-insecure-origin-as-secure=http://test.local"]


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9370
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
         f"--remote-debugging-port={port}", f"--user-data-dir=D:\\_shot\\dg-{int(time.time()*1000)}",
         "--no-proxy-server", "--host-resolver-rules=MAP test.local 127.0.0.1", *EXTRA,
         "--window-size=1280,900", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(80):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5).read()
            break
        except Exception:
            time.sleep(0.4)
    req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
    target = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=90, suppress_origin=True)
    seq = 0

    def send(method, **params):
        nonlocal seq
        seq += 1
        ws.send(json.dumps({"id": seq, "method": method, "params": params}))
        return seq

    send("Runtime.enable")
    send("Log.enable")
    send("Network.enable")
    send("Page.enable")
    send("Emulation.setUserAgentOverride", userAgent=UA, acceptLanguage="ja-JP")
    send("Page.navigate", url="http://test.local/")

    exceptions, failures, console = [], [], []
    end = time.time() + 18
    while time.time() < end:
        try:
            event = json.loads(ws.recv())
        except Exception:
            break
        method = event.get("method", "")
        params = event.get("params", {}) or {}
        if method == "Runtime.exceptionThrown":
            d = params.get("exceptionDetails", {})
            exceptions.append(f"{d.get('text','')} {d.get('exception',{}).get('description','')}"[:220])
        elif method == "Network.loadingFailed":
            failures.append(f"{params.get('type')} {params.get('errorText')}"[:120])
        elif method == "Runtime.consoleAPICalled":
            args = " ".join(str(a.get("value", a.get("description", "")))[:80] for a in params.get("args", []))
            console.append(f"{params.get('type')}: {args}"[:200])

    rid = send("Runtime.evaluate", expression=(
        "JSON.stringify({appLen:(document.querySelector('#app')||{}).innerHTML"
        "? document.querySelector('#app').innerHTML.length : -1,"
        "bodyLen:document.body.innerText.length,"
        "secure:window.isSecureContext,"
        "subtle:!!(window.crypto&&window.crypto.subtle),"
        "loader:!!document.querySelector('.white-overlay-loading'),"
        "title:document.title})"), returnByValue=True)
    dom = ""
    end = time.time() + 15
    while time.time() < end:
        try:
            event = json.loads(ws.recv())
        except Exception:
            break
        if event.get("id") == rid:
            dom = (event.get("result") or {}).get("result", {}).get("value", "")
            break

    print("DOM:", dom)
    print("exceptions:", len(exceptions))
    for item in exceptions[:4]:
        print("   ", item)
    print("net-failures:", len(failures))
    for item in failures[:6]:
        print("   ", item)
    print("console:", len(console))
    for item in console[:4]:
        print("   ", item)
    ws.close()
    proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
