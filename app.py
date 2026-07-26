#!/usr/bin/env python3
"""Lightweight administration server for Gateway Console."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
SOURCE_DIR = ROOT / "sources"
DATA_DIR = Path(os.environ.get("GATEWAY_DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "gateway.db"
SESSION_TTL = 12 * 60 * 60
CAPTCHA_TTL = 5 * 60
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$",
    re.IGNORECASE,
)
PORT_RE = re.compile(r"^[1-9][0-9]{1,4}$")

SOURCE_CATALOG = {
    "landing-page": {
        "id": "landing-page",
        "name": "常胜株LINE 落地页",
        "slug": "landing-page",
        "filename": "landing-page.html",
        "description": "日文股票投资落地页 HTML，依赖 images、css 和 api.php。",
    }
}


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def json_dumps(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
    return f"pbkdf2_sha256$210000${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt), int(rounds)
        )
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


class ClosingConnection(sqlite3.Connection):
    """Commit or roll back, then release the SQLite handle at block exit."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self.initialize()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def initialize(self):
        schema = """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT NOT NULL,
          event_type TEXT NOT NULL CHECK(event_type IN ('visit','click')),
          created_at TEXT NOT NULL, ip TEXT NOT NULL, ua TEXT NOT NULL,
          path TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_events_domain_time ON events(domain, created_at DESC);
        CREATE TABLE IF NOT EXISTS projects (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
          slug TEXT UNIQUE NOT NULL, source_url TEXT NOT NULL DEFAULT '',
          local_path TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'downloaded',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domains (
          id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
          domain TEXT UNIQUE NOT NULL, upstream_port INTEGER NOT NULL,
          frontend_entry TEXT NOT NULL DEFAULT 'logo.gif',
          certificate_status TEXT NOT NULL DEFAULT 'none',
          created_at TEXT NOT NULL,
          FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """
        with self.connect() as db:
            db.executescript(schema)
            try:
                db.execute("ALTER TABLE domains ADD COLUMN frontend_entry TEXT NOT NULL DEFAULT 'logo.gif'")
            except sqlite3.OperationalError:
                pass
            username = os.environ.get("GATEWAY_ADMIN_USER", "admin")
            password = os.environ.get("GATEWAY_ADMIN_PASSWORD", "admin123456")
            db.execute(
                "INSERT OR IGNORE INTO users(username,password_hash,created_at) VALUES(?,?,?)",
                (username, hash_password(password), now_text()),
            )
            defaults = {
                "ipregistry_api_key": "",
                "country_whitelist": "",
                "country_blacklist": "",
                "human_verification": False,
                "block_desktop": True,
                "block_ios": False,
                "block_android": False,
                "ipregistry_enabled": False,
                "blocked_ip_types": ["proxy", "anonymous", "relay"],
                "blocked_threats": ["threat", "abuser", "attacker", "bogon", "tor"],
                "redirect_url": "https://example.com/",
                "frontend_entry": "index.html",
            }
            for key, value in defaults.items():
                db.execute(
                    "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",
                    (key, json.dumps(value), now_text()),
                )

    def user(self, username: str):
        with self.connect() as db:
            return db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()

    def stats(self):
        now = datetime.now().astimezone()
        cutoff = now.replace(hour=22, minute=0, second=0, microsecond=0)
        if now < cutoff:
            cutoff -= timedelta(days=1)
        with self.connect() as db:
            row = db.execute(
                "SELECT SUM(CASE WHEN event_type='visit' THEN 1 ELSE 0 END) total, "
                "SUM(CASE WHEN event_type='visit' AND created_at >= ? THEN 1 ELSE 0 END) today, "
                "SUM(CASE WHEN event_type='visit' THEN 1 ELSE 0 END) visits, "
                "SUM(CASE WHEN event_type='click' THEN 1 ELSE 0 END) clicks FROM events",
                (cutoff.isoformat(timespec="seconds"),),
            ).fetchone()
            domains = db.execute("SELECT COUNT(*) count FROM domains").fetchone()["count"]
        return {
            "today": row["today"] or 0, "total": row["total"] or 0,
            "visits": row["visits"] or 0, "clicks": row["clicks"] or 0,
            "domains": domains, "reset_at": cutoff.isoformat(timespec="seconds"),
        }

    def record_event(self, domain: str, event_type: str, ip: str, ua: str, path: str):
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO events(domain,event_type,created_at,ip,ua,path) VALUES(?,?,?,?,?,?)",
                (domain.lower(), event_type, now_text(), ip[:128], ua[:1024], path[:1024]),
            )
            return cursor.lastrowid

    def events(self, domain: str, event_type: str, page: int, page_size: int):
        filters, args = [], []
        if domain:
            filters.append("domain=?")
            args.append(domain.lower())
        if event_type in ("visit", "click"):
            filters.append("event_type=?")
            args.append(event_type)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) count FROM events" + where, args).fetchone()["count"]
            rows = db.execute(
                "SELECT id,domain,event_type,created_at,ip,ua,path FROM events" + where
                + " ORDER BY id DESC LIMIT ? OFFSET ?",
                (*args, page_size, (page - 1) * page_size),
            ).fetchall()
        return total, [dict(row) for row in rows]

    def domains(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT d.*,p.name project_name FROM domains d LEFT JOIN projects p ON p.id=d.project_id ORDER BY d.id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def add_domain(self, domain: str, port: int, project_id=None, frontend_entry: str = "logo.gif"):
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO domains(project_id,domain,upstream_port,frontend_entry,created_at) VALUES(?,?,?,?,?)",
                (project_id, domain.lower(), port, frontend_entry, now_text()),
            )
            return cursor.lastrowid

    def set_certificate(self, domain: str, status: str):
        with self.connect() as db:
            db.execute("UPDATE domains SET certificate_status=? WHERE domain=?", (status, domain))

    def projects(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM projects ORDER BY id DESC")]

    def project(self, project_id: int):
        with self.connect() as db:
            row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return dict(row) if row else None

    def add_project(self, name: str, slug: str, local_path: str):
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO projects(name,slug,local_path,created_at) VALUES(?,?,?,?)",
                (name, slug, local_path, now_text()),
            )
            return cursor.lastrowid

    def delete_project(self, project_id: int):
        with self.connect() as db:
            cursor = db.execute("DELETE FROM projects WHERE id=?", (project_id,))
            return cursor.rowcount > 0

    def get_settings(self):
        with self.connect() as db:
            rows = db.execute("SELECT key,value FROM settings").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def save_settings(self, values: dict):
        allowed = {
            "ipregistry_api_key", "country_whitelist", "country_blacklist",
            "human_verification", "block_desktop", "block_ios", "block_android",
            "ipregistry_enabled", "blocked_ip_types", "blocked_threats", "redirect_url",
            "frontend_entry",
        }
        with self.connect() as db:
            for key, value in values.items():
                if key in allowed:
                    db.execute(
                        "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                        (key, json.dumps(value), now_text()),
                    )


STORE = Store(DB_PATH)
SESSIONS: dict[str, dict] = {}
CAPTCHAS: dict[str, dict] = {}
MEMORY_LOCK = threading.Lock()


def cleanup_memory():
    now = time.time()
    with MEMORY_LOCK:
        for values in (SESSIONS, CAPTCHAS):
            for key in [key for key, item in values.items() if item["expires"] < now]:
                values.pop(key, None)


class Handler(BaseHTTPRequestHandler):
    server_version = "GatewayConsole/1.0"

    def log_message(self, fmt, *args):
        print(f"[{now_text()}] {self.client_address[0]} {fmt % args}")

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        super().end_headers()

    def json(self, status: int, data, headers: dict | None = None):
        body = json_dumps(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024 * 1024:
            raise ValueError("请求内容过大")
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def cookies(self):
        cookies = SimpleCookie()
        cookies.load(self.headers.get("Cookie", ""))
        return cookies

    def session(self):
        cleanup_memory()
        cookie = self.cookies().get("gateway_session")
        if not cookie:
            return None
        with MEMORY_LOCK:
            return SESSIONS.get(cookie.value)

    def require_auth(self):
        session = self.session()
        if not session:
            self.json(HTTPStatus.UNAUTHORIZED, {"error": "请先登录"})
            return None
        return session

    def client_ip(self):
        forwarded = self.headers.get("X-Forwarded-For", "")
        return forwarded.split(",", 1)[0].strip() or self.client_address[0]

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/api/auth/captcha":
            return self.get_captcha()
        if path == "/api/auth/me":
            session = self.session()
            return self.json(200, {"authenticated": bool(session), "user": session and session["username"]})
        if path in ("/track/visit", "/track/click"):
            return self.track(path.rsplit("/", 1)[-1], query)
        if path == "/guard/check":
            return self.guard_check(query)
        if path.startswith("/api/"):
            if not self.require_auth():
                return
            if path == "/api/dashboard":
                return self.json(200, STORE.stats())
            if path == "/api/events":
                try:
                    page = max(1, int(query.get("page", ["1"])[0] or 1))
                    page_size = min(100, max(10, int(query.get("page_size", ["25"])[0] or 25)))
                except ValueError:
                    return self.json(400, {"error": "分页参数格式不正确"})
                total, rows = STORE.events(
                    query.get("domain", [""])[0], query.get("type", [""])[0], page, page_size
                )
                return self.json(200, {"total": total, "page": page, "items": rows})
            if path == "/api/domains":
                return self.json(200, {"items": STORE.domains()})
            if path == "/api/projects":
                downloaded = {item["slug"] for item in STORE.projects()}
                catalog = [{**item, "downloaded": item["slug"] in downloaded} for item in SOURCE_CATALOG.values()]
                return self.json(200, {"items": STORE.projects(), "catalog": catalog})
            if path == "/api/settings":
                return self.json(200, STORE.get_settings())
            return self.json(404, {"error": "接口不存在"})
        return self.serve_static(path)

    def do_OPTIONS(self):
        if urlparse(self.path).path in ("/track/visit", "/track/click", "/guard/check"):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "86400")
            self.end_headers()
            return
        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            data = self.read_json()
        except (ValueError, json.JSONDecodeError) as exc:
            return self.json(400, {"error": str(exc) or "JSON 格式错误"})
        if path == "/api/auth/login":
            return self.login(data)
        if path in ("/track/visit", "/track/click"):
            return self.track(path.rsplit("/", 1)[-1], data)
        if path == "/api/auth/logout":
            cookie = self.cookies().get("gateway_session")
            if cookie:
                with MEMORY_LOCK:
                    SESSIONS.pop(cookie.value, None)
            return self.json(200, {"ok": True}, {"Set-Cookie": "gateway_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"})
        if not self.require_auth():
            return
        if path == "/api/domains":
            return self.create_domain(data)
        if path == "/api/certificates":
            return self.issue_certificate(data)
        if path == "/api/projects/import":
            return self.import_project(data)
        if path == "/api/catalog/download":
            return self.download_catalog(data)
        match = re.fullmatch(r"/api/projects/(\d+)/update", path)
        if match:
            return self.update_project(int(match.group(1)))
        if path == "/api/settings":
            STORE.save_settings(data)
            return self.json(200, {"ok": True})
        return self.json(404, {"error": "接口不存在"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if not self.require_auth():
            return
        match = re.fullmatch(r"/api/projects/(\d+)", parsed.path)
        if match:
            if not STORE.delete_project(int(match.group(1))):
                return self.json(404, {"error": "源码不存在"})
            return self.json(200, {"ok": True})
        self.json(404, {"error": "接口不存在"})

    def get_captcha(self):
        cleanup_memory()
        left, right = secrets.randbelow(8) + 1, secrets.randbelow(8) + 1
        operation = secrets.choice(("+", "+", "-"))
        if operation == "-" and right > left:
            left, right = right, left
        answer = left + right if operation == "+" else left - right
        captcha_id = secrets.token_urlsafe(18)
        with MEMORY_LOCK:
            CAPTCHAS[captcha_id] = {"answer": str(answer), "expires": time.time() + CAPTCHA_TTL}
        self.json(200, {"id": captcha_id, "question": f"{left} {operation} {right} = ?"})

    def login(self, data):
        captcha_id = str(data.get("captcha_id", ""))
        with MEMORY_LOCK:
            captcha = CAPTCHAS.pop(captcha_id, None)
        if not captcha or captcha["expires"] < time.time() or not hmac.compare_digest(
            str(data.get("captcha", "")).strip(), captcha["answer"]
        ):
            return self.json(400, {"error": "验证码错误或已过期"})
        username = str(data.get("username", "")).strip()
        user = STORE.user(username)
        if not user or not verify_password(str(data.get("password", "")), user["password_hash"]):
            time.sleep(0.25)
            return self.json(401, {"error": "用户名或密码错误"})
        token = secrets.token_urlsafe(32)
        with MEMORY_LOCK:
            SESSIONS[token] = {"username": username, "expires": time.time() + SESSION_TTL}
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        self.json(200, {"ok": True, "username": username}, {
            "Set-Cookie": f"gateway_session={token}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; SameSite=Strict{secure}"
        })

    def track(self, event_type: str, source):
        domain = source.get("domain", [""])[0] if isinstance(source.get("domain"), list) else source.get("domain", "")
        domain = str(domain).lower().strip()
        if not DOMAIN_RE.match(domain):
            return self.json(400, {"error": "域名格式不正确"})
        path = source.get("path", [""])[0] if isinstance(source.get("path"), list) else source.get("path", "")
        event_id = STORE.record_event(domain, event_type, self.client_ip(), self.headers.get("User-Agent", ""), str(path))
        return self.json(201, {"ok": True, "id": event_id}, {"Access-Control-Allow-Origin": "*"})

    def guard_check(self, query):
        settings = STORE.get_settings()
        ua = self.headers.get("User-Agent", "").lower()
        reasons = []
        if settings.get("block_desktop") and not re.search(r"android|iphone|ipad|mobile", ua):
            reasons.append("desktop")
        if settings.get("block_ios") and re.search(r"iphone|ipad|ipod", ua):
            reasons.append("ios")
        if settings.get("block_android") and "android" in ua:
            reasons.append("android")

        registry = None
        key = settings.get("ipregistry_api_key", "")
        if settings.get("ipregistry_enabled") and key:
            ip = self.client_ip()
            url = f"https://api.ipregistry.co/{ip}?key={key}"
            try:
                request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "GatewayConsole/1.0"})
                with urllib.request.urlopen(request, timeout=6) as response:
                    registry = json.loads(response.read().decode("utf-8"))
                country = str(registry.get("location", {}).get("country", {}).get("code", "")).upper()
                whitelist = {item for item in re.split(r"[\s,]+", settings.get("country_whitelist", "").upper()) if item}
                blacklist = {item for item in re.split(r"[\s,]+", settings.get("country_blacklist", "").upper()) if item}
                if whitelist and country not in whitelist:
                    reasons.append("country_not_allowed")
                if country and country in blacklist:
                    reasons.append("country_blocked")
                security = registry.get("security", {})
                type_fields = {"proxy": "is_proxy", "vpn": "is_vpn", "anonymous": "is_anonymous", "relay": "is_relay", "cloud": "is_cloud_provider"}
                threat_fields = {"threat": "is_threat", "abuser": "is_abuser", "attacker": "is_attacker", "bogon": "is_bogon", "tor": "is_tor"}
                for selected, fields, prefix in (
                    (settings.get("blocked_ip_types", []), type_fields, "network"),
                    (settings.get("blocked_threats", []), threat_fields, "threat"),
                ):
                    for name in selected:
                        if security.get(fields.get(name, "")):
                            reasons.append(f"{prefix}:{name}")
            except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                return self.json(502, {"error": "IPRegistry 检测暂时不可用", "detail": str(exc)}, {"Access-Control-Allow-Origin": "*"})

        return self.json(200, {
            "allowed": not reasons,
            "reasons": reasons,
            "redirect_url": settings.get("redirect_url", "") if reasons else "",
            "human_verification": bool(settings.get("human_verification")) and not reasons,
            "country": registry and registry.get("location", {}).get("country", {}).get("code", ""),
        }, {"Access-Control-Allow-Origin": "*"})

    def create_domain(self, data):
        domain = str(data.get("domain", "")).lower().strip().rstrip(".")
        port_text = str(data.get("upstream_port", ""))
        frontend_entry = str(data.get("frontend_entry", "logo.gif")).strip().lstrip("/") or "logo.gif"
        if not DOMAIN_RE.match(domain):
            return self.json(400, {"error": "请输入有效的完整域名"})
        if ".." in frontend_entry or "\\" in frontend_entry or frontend_entry.startswith("."):
            return self.json(400, {"error": "前台入口只能填写站点内的文件路径"})
        if not PORT_RE.match(port_text) or int(port_text) > 65535:
            return self.json(400, {"error": "入口端口必须是 10 到 65535 之间的数字"})
        port = int(port_text)
        try:
            domain_id = STORE.add_domain(domain, port, data.get("project_id"), frontend_entry)
        except sqlite3.IntegrityError:
            return self.json(409, {"error": "该域名已经存在"})
        helper = os.environ.get("GATEWAY_DOMAIN_HELPER", "")
        configured = False
        if helper:
            try:
                subprocess.run(self.helper_command(helper, "configure", domain, str(port)), check=True, timeout=30)
                configured = True
            except (OSError, subprocess.SubprocessError) as exc:
                return self.json(502, {"error": f"域名已保存，但 Nginx 配置失败：{exc}", "id": domain_id})
        return self.json(201, {"ok": True, "id": domain_id, "nginx_configured": configured})

    def issue_certificate(self, data):
        domain = str(data.get("domain", "")).lower().strip()
        if not DOMAIN_RE.match(domain) or domain not in {item["domain"] for item in STORE.domains()}:
            return self.json(400, {"error": "请先添加有效域名"})
        helper = os.environ.get("GATEWAY_DOMAIN_HELPER", "")
        if not helper:
            return self.json(503, {"error": "当前环境未配置证书助手，部署后可用"})
        try:
            subprocess.run(self.helper_command(helper, "certificate", domain), check=True, timeout=180)
            STORE.set_certificate(domain, "active")
            return self.json(200, {"ok": True, "status": "active"})
        except subprocess.TimeoutExpired:
            STORE.set_certificate(domain, "failed")
            return self.json(504, {"error": "证书申请超时，请检查域名 DNS"})
        except (OSError, subprocess.CalledProcessError) as exc:
            STORE.set_certificate(domain, "failed")
            return self.json(502, {"error": f"证书申请失败：{exc}"})

    @staticmethod
    def helper_command(helper: str, *args: str):
        command = [helper, *args]
        if os.environ.get("GATEWAY_HELPER_USE_SUDO") == "1":
            command = ["/usr/bin/sudo", "-n", *command]
        return command

    def import_project(self, data):
        name = str(data.get("name", "")).strip()
        slug = re.sub(r"[^a-z0-9-]", "-", str(data.get("slug", "")).lower()).strip("-")
        local_path = str(data.get("local_path", "")).strip()
        if not name or not slug or not local_path.startswith("/"):
            return self.json(400, {"error": "请填写名称、英文标识和服务器绝对路径"})
        try:
            project_id = STORE.add_project(name[:100], slug[:80], local_path[:500])
        except sqlite3.IntegrityError:
            return self.json(409, {"error": "英文标识已存在"})
        return self.json(201, {"ok": True, "id": project_id})

    def download_catalog(self, data):
        source_id = str(data.get("source_id", "")).strip()
        source = SOURCE_CATALOG.get(source_id)
        if not source:
            return self.json(404, {"error": "源码不存在"})
        source_file = (SOURCE_DIR / source["filename"]).resolve()
        if SOURCE_DIR.resolve() not in source_file.parents or not source_file.is_file():
            return self.json(500, {"error": "源码文件未随安装包提供"})
        local_path = (DATA_DIR / "projects" / source["slug"]).resolve()
        try:
            local_path.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, local_path / "index.html")
            project_id = STORE.add_project(source["name"], source["slug"], str(local_path))
        except sqlite3.IntegrityError:
            return self.json(409, {"error": "该源码已经下载"})
        except OSError as exc:
            return self.json(500, {"error": f"源码保存失败：{exc}"})
        return self.json(201, {"ok": True, "id": project_id, "local_path": str(local_path)})

    def update_project(self, project_id: int):
        project = STORE.project(project_id)
        if not project:
            return self.json(404, {"error": "源码记录不存在"})
        source = next((item for item in SOURCE_CATALOG.values() if item["slug"] == project["slug"]), None)
        if not source:
            return self.json(400, {"error": "该项目不是内置源码，不能自动更新"})
        source_file = (SOURCE_DIR / source["filename"]).resolve()
        target_dir = Path(project["local_path"]).resolve()
        if SOURCE_DIR.resolve() not in source_file.parents or not source_file.is_file():
            return self.json(500, {"error": "源码文件未随安装包提供"})
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, target_dir / "index.html")
        except OSError as exc:
            return self.json(500, {"error": f"源码更新失败：{exc}"})
        return self.json(200, {"ok": True, "updated_at": now_text()})

    def serve_static(self, path: str):
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        file_path = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in file_path.parents and file_path != STATIC_DIR.resolve():
            return self.send_error(403)
        if not file_path.is_file():
            file_path = STATIC_DIR / "index.html"
        content = file_path.read_bytes()
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache" if file_path.name == "index.html" else "public, max-age=3600")
        self.end_headers()
        self.wfile.write(content)


def main():
    parser = argparse.ArgumentParser(description="Gateway Console")
    parser.add_argument("--host", default=os.environ.get("GATEWAY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("GATEWAY_PORT", "8787")))
    parser.add_argument("--reset-password", help="Reset an administrator password and exit")
    parser.add_argument("--reset-user", default="admin", help="Username to reset")
    args = parser.parse_args()
    if args.reset_password is not None:
        if len(args.reset_password) < 10:
            parser.error("--reset-password must contain at least 10 characters")
        with STORE.connect() as db:
            cursor = db.execute("UPDATE users SET password_hash=? WHERE username=?", (hash_password(args.reset_password), args.reset_user))
            if cursor.rowcount != 1:
                parser.error(f"user not found: {args.reset_user}")
        print(f"Password reset for {args.reset_user}")
        return
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Gateway Console listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
