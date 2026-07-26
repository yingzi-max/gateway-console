import http.cookiejar
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import app


class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["GATEWAY_ADMIN_USER"] = "admin"
        os.environ["GATEWAY_ADMIN_PASSWORD"] = "admin123456"
        app.DATA_DIR = Path(cls.temp.name) / "data"
        app.STORE = app.Store(Path(cls.temp.name) / "test.db")
        app.SESSIONS.clear()
        app.CAPTCHAS.clear()
        cls.server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        jar = http.cookiejar.CookieJar()
        cls.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    @classmethod
    def request(cls, path, method="GET", body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(cls.base + path, data=data, method=method)
        if data:
            request.add_header("Content-Type", "application/json")
        try:
            response = cls.opener.open(request)
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())
        with response:
            return response.status, json.loads(response.read())

    def test_complete_flow(self):
        _, captcha = self.request("/api/auth/captcha")
        left, operator, right, _, _ = captcha["question"].split()
        answer = int(left) + int(right) if operator == "+" else int(left) - int(right)
        status, result = self.request("/api/auth/login", "POST", {
            "username": "admin", "password": "admin123456",
            "captcha_id": captcha["id"], "captcha": str(answer),
        })
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])

        status, result = self.request("/track/visit?domain=example.com&path=/home")
        self.assertEqual(status, 201)
        self.assertGreater(result["id"], 0)

        _, dashboard = self.request("/api/dashboard")
        self.assertEqual(dashboard["total"], 1)
        self.assertEqual(dashboard["visits"], 1)

        _, events = self.request("/api/events?domain=example.com")
        self.assertEqual(events["total"], 1)
        self.assertEqual(events["items"][0]["domain"], "example.com")

        status, domain = self.request("/api/domains", "POST", {
            "domain": "site.example.com", "upstream_port": 8080,
        })
        self.assertEqual(status, 201)
        self.assertFalse(domain["nginx_configured"])

        status, updated_domain = self.request("/api/domains", "POST", {
            "domain": "site.example.com", "frontend_entry": "images/logo.gif",
        })
        self.assertEqual(status, 201)
        self.assertEqual(updated_domain["id"], domain["id"])
        self.assertEqual(app.STORE.domains()[0]["frontend_entry"], "images/logo.gif")

        status, saved = self.request("/api/settings", "POST", {
            "country_blacklist": "US, GB", "block_android": True,
        })
        self.assertEqual(status, 200)
        self.assertTrue(saved["ok"])
        _, settings = self.request("/api/settings")
        self.assertEqual(settings["country_blacklist"], "US, GB")
        self.assertTrue(settings["block_android"])

        status, downloaded = self.request("/api/catalog/download", "POST", {"source_id": "landing-page"})
        self.assertEqual(status, 201)
        self.assertTrue(Path(downloaded["local_path"], "index.html").is_file())
        _, projects = self.request("/api/projects")
        self.assertEqual(len(projects["items"]), 1)
        self.assertTrue(projects["catalog"][0]["downloaded"])

        status, updated = self.request("/api/projects/1/update", "POST", {})
        self.assertEqual(status, 200)
        self.assertTrue(updated["ok"])

        status, duplicate = self.request("/api/catalog/download", "POST", {"source_id": "landing-page"})
        self.assertEqual(status, 409)
        self.assertIn("已经下载", duplicate["error"])

        status, deleted = self.request("/api/projects/1", "DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(deleted["ok"])

    def test_ipregistry_status_reads_real_credit_balance_header(self):
        class StatusResponse:
            headers = {
                "Ipregistry-Credits-Remaining": "54179",
                "Ipregistry-Credits-Consumed": "1",
            }

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            @staticmethod
            def read():
                return b"{}"

        app.STORE.save_settings({"ipregistry_api_key": "test-key"})
        with mock.patch("app.urllib.request.urlopen", return_value=StatusResponse()) as urlopen:
            status, result = self.request("/api/ipregistry/status")
        self.assertEqual(status, 200)
        self.assertEqual(result["remaining"], 54179)
        self.assertEqual(result["consumed"], 1)
        self.assertIn("key=test-key", urlopen.call_args.args[0].full_url)

        app.STORE.save_settings({"ipregistry_api_key": ""})
        status, result = self.request("/api/ipregistry/status")
        self.assertEqual(status, 200)
        self.assertFalse(result["configured"])
        self.assertIsNone(result["remaining"])

    def test_country_select_ui_and_whitelist_explanation_are_bundled(self):
        html = (app.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        script = (app.STATIC_DIR / "app.js").read_text(encoding="utf-8")
        self.assertEqual(html.count("data-country-select"), 2)
        self.assertIn("未选择的所有国家会自动加入黑名单", html)
        self.assertIn("COUNTRY_CODES", script)
        self.assertIn("setCountrySelectValue", script)

    def test_existing_event_database_migrates_rejected_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "legacy.db"
            with sqlite3.connect(database, factory=app.ClosingConnection) as db:
                db.executescript("""
                CREATE TABLE events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT NOT NULL,
                  event_type TEXT NOT NULL CHECK(event_type IN ('visit','click')),
                  created_at TEXT NOT NULL, ip TEXT NOT NULL, ua TEXT NOT NULL,
                  path TEXT NOT NULL DEFAULT ''
                );
                INSERT INTO events(domain,event_type,created_at,ip,ua,path)
                  VALUES('legacy.example','visit','2026-07-26T23:00:00+08:00','127.0.0.1','Legacy','/');
                """)
            store = app.Store(database)
            store.record_event("legacy.example", "rejected", "203.0.113.5", "Scanner", "/")
            rejected_total, rejected = store.events("legacy.example", "rejected", 1, 25)
            self.assertEqual(rejected_total, 1)
            self.assertEqual(rejected[0]["event_type"], "rejected")
            self.assertEqual(store.stats()["total"], 1)

    def test_domain_helper_and_certificate_commands(self):
        project_root = Path(self.temp.name) / "helper-project"
        project_root.mkdir(parents=True, exist_ok=True)
        (project_root / "index.html").write_text("<html></html>", encoding="utf-8")
        project_id = app.STORE.add_project("Helper", "landing-page", str(project_root))
        completed = mock.Mock(stdout="", stderr="")
        with mock.patch.dict(os.environ, {
            "GATEWAY_DOMAIN_HELPER": "/usr/local/sbin/gateway-domain-helper",
            "GATEWAY_HELPER_USE_SUDO": "1",
        }, clear=False), mock.patch("app.subprocess.run", return_value=completed) as run:
            status, configured = self.request("/api/domains", "POST", {
                "domain": "helper.example.com",
                "project_id": project_id,
                "frontend_entry": "logo.gif",
            })
            self.assertEqual(status, 201)
            self.assertTrue(configured["nginx_configured"])
            self.assertEqual(configured["hosting_mode"], "static")
            self.assertEqual(run.call_args.args[0], [
                "/usr/bin/sudo", "-n", "/usr/local/sbin/gateway-domain-helper",
                "configure-static", "helper.example.com", str(project_root), "logo.gif",
            ])

            status, certificate = self.request("/api/certificates", "POST", {
                "domain": "helper.example.com",
            })
            self.assertEqual(status, 200)
            self.assertEqual(certificate["status"], "active")
            self.assertEqual(run.call_args.args[0], [
                "/usr/bin/sudo", "-n", "/usr/local/sbin/gateway-domain-helper",
                "certificate", "helper.example.com", str(project_root), "logo.gif",
            ])

        status, invalid = self.request("/api/domains", "POST", {
            "domain": "badpath.example.com",
            "project_id": project_id,
            "frontend_entry": "../secret.html",
        })
        self.assertEqual(status, 400)
        self.assertIn("前台入口", invalid["error"])

    def test_guard_device_switches_and_missing_registry_key(self):
        app.STORE.save_settings({
            "block_desktop": False,
            "block_ios": True,
            "block_android": False,
            "ipregistry_enabled": False,
            "country_whitelist": "",
            "country_blacklist": "",
        })
        ios_request = urllib.request.Request(
            self.base + "/guard/check",
            headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile"},
        )
        with self.opener.open(ios_request) as response:
            ios = json.loads(response.read())
        self.assertFalse(ios["allowed"])
        self.assertIn("ios", ios["reasons"])

        app.STORE.save_settings({"block_ios": False, "block_android": True})
        android_request = urllib.request.Request(
            self.base + "/guard/check",
            headers={"User-Agent": "Mozilla/5.0 (Linux; Android 15) Mobile"},
        )
        with self.opener.open(android_request) as response:
            android = json.loads(response.read())
        self.assertFalse(android["allowed"])
        self.assertIn("android", android["reasons"])

        app.STORE.save_settings({
            "block_android": False,
            "ipregistry_enabled": True,
            "ipregistry_api_key": "",
        })
        status, missing_key = self.request("/guard/check")
        self.assertEqual(status, 502)
        self.assertIn("IPRegistry", missing_key["error"])
        app.STORE.save_settings({"ipregistry_enabled": False})

    def test_public_frontend_records_visits_and_rotates_links(self):
        public_root = Path(self.temp.name) / "public-project"
        public_root.mkdir(parents=True, exist_ok=True)
        (public_root / "logo.gif").write_text("<html><body><a href='https://original.example/'>Go</a></body></html>", encoding="utf-8")
        (public_root / "images").mkdir()
        (public_root / "images" / "1.jpg").write_bytes(b"test-image")
        project_id = app.STORE.add_project("Public", "public-project", str(public_root))
        app.STORE.add_domain("public.example.com", 80, project_id, "logo.gif")
        app.STORE.save_settings({
            "block_desktop": False,
            "ipregistry_enabled": False,
            "ipregistry_api_key": "",
            "country_whitelist": "",
            "country_blacklist": "",
            "redirect_links": [
                {"url": "https://first.example/", "limit": 1},
                {"url": "https://second.example/", "limit": 0},
            ],
        })
        request = urllib.request.Request(
            self.base + "/logo.gif",
            headers={"Host": "public.example.com", "User-Agent": "Mozilla/5.0"},
        )
        visits_before = app.STORE.stats()["total"]
        with self.opener.open(request) as response:
            self.assertEqual(response.headers.get_content_type(), "text/html")
            self.assertIn(b"/__gateway/click", response.read())
        self.assertEqual(app.STORE.stats()["total"], visits_before + 1)

        asset_visits_before = app.STORE.stats()["total"]
        asset_request = urllib.request.Request(
            self.base + "/images/1.jpg",
            headers={"Host": "public.example.com", "User-Agent": "Mozilla/5.0"},
        )
        with self.opener.open(asset_request) as response:
            self.assertEqual(response.headers.get_content_type(), "image/jpeg")
            self.assertEqual(response.read(), b"test-image")
        self.assertEqual(app.STORE.stats()["total"], asset_visits_before)

        isolated_request = urllib.request.Request(
            self.base + "/api/auth/captcha",
            headers={"Host": "public.example.com"},
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.opener.open(isolated_request)
        self.assertEqual(raised.exception.code, 404)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, new):
                return None

        click_opener = urllib.request.build_opener(NoRedirect())
        clicks_before = app.STORE.stats()["clicks"]
        for expected in ("https://first.example/", "https://second.example/"):
            click_request = urllib.request.Request(
                self.base + "/__gateway/click",
                headers={"Host": "public.example.com", "User-Agent": "Mozilla/5.0"},
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                click_opener.open(click_request)
            self.assertEqual(raised.exception.code, 302)
            self.assertEqual(raised.exception.headers["Location"], expected)
        self.assertEqual(app.STORE.stats()["clicks"], clicks_before + 2)

        app.STORE.save_settings({
            "block_desktop": True,
            "redirect_url": "https://blocked.example/",
        })
        blocked_request = urllib.request.Request(
            self.base + "/logo.gif",
            headers={"Host": "public.example.com", "User-Agent": "Mozilla/5.0 Desktop"},
        )
        blocked_visits_before = app.STORE.stats()["total"]
        with self.assertRaises(urllib.error.HTTPError) as raised:
            click_opener.open(blocked_request)
        self.assertEqual(raised.exception.code, 302)
        self.assertEqual(raised.exception.headers["Location"], "https://blocked.example/")
        self.assertEqual(app.STORE.stats()["total"], blocked_visits_before)
        rejected_total, rejected = app.STORE.events("public.example.com", "rejected", 1, 25)
        self.assertEqual(rejected_total, 1)
        self.assertIn("Desktop", rejected[0]["ua"])

        class RegistryResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            @staticmethod
            def read():
                return json.dumps({
                    "location": {"country": {"code": "US"}},
                    "security": {"is_proxy": True, "is_threat": True},
                }).encode()

        app.STORE.save_settings({
            "block_desktop": False,
            "ipregistry_enabled": False,
            "ipregistry_api_key": "test-key",
            "country_whitelist": "JP",
            "country_blacklist": "",
        })
        foreign_visits_before = app.STORE.stats()["total"]
        with mock.patch("app.urllib.request.urlopen", return_value=RegistryResponse()):
            with self.assertRaises(urllib.error.HTTPError) as raised:
                click_opener.open(request)
        self.assertEqual(raised.exception.code, 302)
        self.assertEqual(raised.exception.headers["Location"], "https://blocked.example/")
        self.assertEqual(app.STORE.stats()["total"], foreign_visits_before)
        rejected_total, rejected = app.STORE.events("public.example.com", "rejected", 1, 25)
        self.assertEqual(rejected_total, 2)
        self.assertEqual(rejected[0]["event_type"], "rejected")

        app.STORE.save_settings({
            "block_desktop": False,
            "ipregistry_enabled": True,
            "ipregistry_api_key": "test-key",
            "country_whitelist": "CN",
            "blocked_ip_types": ["proxy"],
            "blocked_threats": ["threat"],
        })
        guard_request = urllib.request.Request(
            self.base + "/guard/check",
            headers={"Host": "public.example.com", "User-Agent": "Mozilla/5.0 Android Mobile"},
        )
        with mock.patch("app.urllib.request.urlopen", return_value=RegistryResponse()):
            with self.opener.open(guard_request) as response:
                decision = json.loads(response.read())
        self.assertFalse(decision["allowed"])
        self.assertIn("country_not_allowed", decision["reasons"])
        self.assertIn("network:proxy", decision["reasons"])
        self.assertIn("threat:threat", decision["reasons"])

        app.STORE.save_settings({
            "ipregistry_enabled": False,
            "country_whitelist": "",
            "country_blacklist": "",
            "blocked_ip_types": [],
            "blocked_threats": [],
            "redirect_links": [],
        })
        original_request = urllib.request.Request(
            self.base + "/logo.gif",
            headers={"Host": "public.example.com", "User-Agent": "Mozilla/5.0 Mobile"},
        )
        with self.opener.open(original_request) as response:
            original_html = response.read()
        self.assertIn(b"https://original.example/", original_html)
        self.assertNotIn(b"/__gateway/click", original_html)

    def test_redirect_link_validation(self):
        status, saved = self.request("/api/settings", "POST", {
            "redirect_links": [
                {"url": "javascript:alert(1)", "limit": 1},
                {"url": "https://valid.example/path", "limit": "5"},
                {"url": "https://negative.example/", "limit": -1},
            ],
        })
        self.assertEqual(status, 200)
        self.assertTrue(saved["ok"])
        _, settings = self.request("/api/settings")
        self.assertEqual(settings["redirect_links"], [{
            "url": "https://valid.example/path",
            "limit": 5,
        }])

    def test_bundled_landing_page_has_no_external_redirector(self):
        source = (app.SOURCE_DIR / "landing-page" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("link.ccsyshub.com/api/sdk.js", source)


if __name__ == "__main__":
    unittest.main()
