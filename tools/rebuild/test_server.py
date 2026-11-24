"""本地测试用服务：monkeypatch 掉登录验证码，仅用于验证接口/UI，不进入生产代码。"""
import sys
from http.server import ThreadingHTTPServer

sys.path.insert(0, r"D:\deepseek-harness工作区\gateway-console")
import app  # noqa: E402

original_login = app.Handler.login


def patched_login(self, data):
    username = str((data or {}).get("username", "")).strip() or "admin"
    import secrets
    import time as _t
    token = secrets.token_urlsafe(32)
    with app.MEMORY_LOCK:
        app.SESSIONS[token] = {"username": username, "expires": _t.time() + app.SESSION_TTL}
    self.json(200, {"ok": True, "username": username}, {
        "Set-Cookie": f"gateway_session={token}; Path=/; Max-Age={app.SESSION_TTL}; HttpOnly; SameSite=Strict"
    })


app.Handler.login = patched_login

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    server = ThreadingHTTPServer(("127.0.0.1", port), app.Handler)
    print(f"test server on http://127.0.0.1:{port}  (captcha bypassed)", flush=True)
    server.serve_forever()
