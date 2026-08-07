from __future__ import annotations

import http.client
import importlib.util
import json
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "shared"), str(ROOT / "skills" / "kaoyan-question-builder" / "scripts")]

from tests.test_question_builder import make_pdf


def load_server():
    path = ROOT / "skills" / "kaoyan-question-builder" / "scripts" / "serve.py"
    spec = importlib.util.spec_from_file_location("question_builder_server", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def open_session(connection: http.client.HTTPConnection) -> tuple[str, str]:
    connection.request("GET", "/")
    response = connection.getresponse()
    response.read()
    if response.status != 200:
        raise AssertionError(f"App shell returned HTTP {response.status}")
    set_cookie = response.getheader("Set-Cookie") or ""
    return set_cookie.split(";", 1)[0], set_cookie


def json_request(
    connection: http.client.HTTPConnection,
    method: str,
    path: str,
    payload: dict,
    cookie: str,
    extra_headers: dict[str, str] | None = None,
) -> tuple[http.client.HTTPResponse, dict]:
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "Content-Length": str(len(body)), "Cookie": cookie}
    headers.update(extra_headers or {})
    connection.request(method, path, body, headers)
    response = connection.getresponse()
    value = json.loads(response.read().decode())
    return response, value


class HttpWorkflowTests(unittest.TestCase):
    def test_upload_patch_recover_and_missing_provider(self) -> None:
        module = load_server()
        with tempfile.TemporaryDirectory() as temp:
            module.STORE = module.ProjectStore(Path(temp))
            module.PROVIDER_CONFIG = module.ProviderConfig(api_key_env="DEFINITELY_MISSING")
            server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=30)
                cookie, _ = open_session(connection)
                source = Path(temp) / "questions.pdf"
                make_pdf(source)
                boundary = "----" + uuid.uuid4().hex
                parts = []
                for name, value in (("title", "HTTP 题集"), ("subject", "数学")):
                    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
                parts.append(
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"pdf\"; filename=\"questions.pdf\"\r\n"
                    "Content-Type: application/pdf\r\n\r\n".encode() + source.read_bytes() + b"\r\n"
                )
                parts.append(f"--{boundary}--\r\n".encode())
                parts.insert(-1, parts[-2])
                body = b"".join(parts)
                connection.request("POST", "/api/projects", body, {
                    "Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body)),
                    "Cookie": cookie,
                })
                response = connection.getresponse()
                project = json.loads(response.read().decode())
                self.assertEqual(response.status, 201, project)
                self.assertEqual(project["title"], "HTTP 题集")
                self.assertEqual(len(project["pages"]), 4)
                self.assertEqual(len(project["candidates"]), 6)
                self.assertEqual([value["name"] for value in project["source_pdfs"]], ["questions.pdf", "questions-2.pdf"])

                item = project["candidates"][0]
                stale_revision = project["revision"]
                response, changed = json_request(
                    connection,
                    "PATCH",
                    f"/api/projects/{project['project_id']}/candidates/{item['id']}",
                    {"bbox": [0.1, 0.1, 0.8, 0.4], "selected": True, "revision": stale_revision},
                    cookie,
                )
                self.assertEqual(response.status, 200)
                self.assertEqual(changed["candidates"][0]["bbox"], [0.1, 0.1, 0.8, 0.4])
                self.assertGreater(changed["revision"], stale_revision)

                response, conflict = json_request(
                    connection,
                    "PATCH",
                    f"/api/projects/{project['project_id']}/candidates/{item['id']}",
                    {"question_number": "stale", "revision": stale_revision},
                    cookie,
                )
                self.assertEqual(response.status, 409, conflict)

                connection.request("GET", f"/api/projects/{project['project_id']}", headers={"Cookie": cookie})
                response = connection.getresponse()
                recovered = json.loads(response.read().decode())
                self.assertEqual(recovered["candidates"][0]["bbox"], [0.1, 0.1, 0.8, 0.4])
                self.assertNotEqual(recovered["candidates"][0]["question_number"], "stale")

                response, error = json_request(
                    connection,
                    "POST",
                    f"/api/projects/{project['project_id']}/recognize",
                    {
                        "ids": [item["id"]],
                        "revision": recovered["revision"],
                        "provider": {"base_url": "https://attacker.invalid", "api_key_env": "PATH"},
                    },
                    cookie,
                )
                self.assertEqual(response.status, 400)
                self.assertIn("fixed when the server starts", error["error"])

                response, error = json_request(
                    connection,
                    "POST",
                    f"/api/projects/{project['project_id']}/recognize",
                    {"ids": [item["id"]], "revision": recovered["revision"]},
                    cookie,
                )
                self.assertEqual(response.status, 400)
                self.assertIn("manual transcription", error["error"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_loopback_session_origin_and_static_path_guards(self) -> None:
        module = load_server()
        with tempfile.TemporaryDirectory() as temp:
            module.STORE = module.ProjectStore(Path(temp))
            server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
                connection.request("GET", "/api/projects")
                response = connection.getresponse()
                response.read()
                self.assertEqual(response.status, 403)

                cookie, set_cookie = open_session(connection)
                self.assertIn("HttpOnly", set_cookie)
                self.assertIn("SameSite=Strict", set_cookie)

                connection.request("GET", "/assets/..%2Fscripts%2Fserve.py", headers={"Cookie": cookie})
                response = connection.getresponse()
                leaked = response.read()
                self.assertNotEqual(response.status, 200)
                self.assertNotIn(b"Kaoyan Question Builder web application", leaked)

                connection.request("POST", "/api/projects", b"", {
                    "Content-Length": "0",
                    "Cookie": cookie,
                    "Origin": "http://attacker.example",
                })
                response = connection.getresponse()
                response.read()
                self.assertEqual(response.status, 403)

                hostile_host = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
                hostile_host.putrequest("GET", "/", skip_host=True)
                hostile_host.putheader("Host", f"attacker.example:{server.server_port}")
                hostile_host.endheaders()
                response = hostile_host.getresponse()
                response.read()
                self.assertEqual(response.status, 403)
                hostile_host.close()

                with self.assertRaises(module.argparse.ArgumentTypeError):
                    module.loopback_bind_host("0.0.0.0")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_recognition_is_selected_only_and_requires_explicit_replace(self) -> None:
        module = load_server()
        with tempfile.TemporaryDirectory() as temp:
            module.STORE = module.ProjectStore(Path(temp))
            startup_config = module.ProviderConfig(
                base_url="https://startup.example/v1",
                model="startup-model",
                api_key_env="STARTUP_KEY",
            )
            module.PROVIDER_CONFIG = startup_config
            project = module.STORE.create({
                "title": "recognition",
                "source_pdfs": [],
                "pages": [],
                "layout": {},
                "candidates": [
                    {
                        "id": "q-selected",
                        "selected": True,
                        "pdf_page": 1,
                        "bbox": [0.1, 0.1, 0.9, 0.9],
                        "subquestions_detected": 0,
                        "answer_suspect": False,
                    },
                    {
                        "id": "q-unselected",
                        "selected": False,
                        "pdf_page": 1,
                        "bbox": [0.1, 0.1, 0.9, 0.9],
                        "subquestions_detected": 0,
                        "answer_suspect": False,
                    },
                ],
            })
            page = module.STORE.find_dir(project["project_id"]) / "pages" / "page-1.png"
            page.parent.mkdir()
            Image.new("RGB", (200, 200), "white").save(page)
            fake_provider = mock.Mock()
            fake_provider.analyze.side_effect = lambda *args: {
                "stem": "recognized",
                "options": [],
                "subquestions": [],
                "uncertainties": [],
                "graphics": [],
                "suspected_answer_leak": False,
            }
            with mock.patch.object(module, "VisionProvider", return_value=fake_provider) as provider_factory:
                server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
                    cookie, _ = open_session(connection)
                    endpoint = f"/api/projects/{project['project_id']}/recognize"

                    response, error = json_request(connection, "POST", endpoint, {
                        "ids": ["q-selected"],
                        "revision": project["revision"],
                        "provider": {"base_url": "https://attacker.invalid", "api_key_env": "PATH"},
                    }, cookie)
                    self.assertEqual(response.status, 400, error)
                    provider_factory.assert_not_called()

                    response, error = json_request(connection, "POST", endpoint, {
                        "ids": ["q-unselected"], "revision": project["revision"],
                    }, cookie)
                    self.assertEqual(response.status, 400, error)
                    provider_factory.assert_not_called()

                    response, recognized = json_request(
                        connection, "POST", endpoint, {"revision": project["revision"]}, cookie,
                    )
                    self.assertEqual(response.status, 200, recognized)
                    provider_factory.assert_called_once_with(startup_config)
                    self.assertEqual(fake_provider.analyze.call_count, 1)
                    self.assertEqual(recognized["candidates"][0]["transcription"]["stem"], "recognized")
                    self.assertNotIn("transcription", recognized["candidates"][1])

                    response, error = json_request(connection, "POST", endpoint, {
                        "ids": ["q-selected"], "revision": recognized["revision"],
                    }, cookie)
                    self.assertEqual(response.status, 400, error)
                    self.assertIn("replace_existing=true", error["error"])
                    self.assertEqual(fake_provider.analyze.call_count, 1)

                    response, replaced = json_request(connection, "POST", endpoint, {
                        "ids": ["q-selected"],
                        "revision": recognized["revision"],
                        "replace_existing": True,
                    }, cookie)
                    self.assertEqual(response.status, 200, replaced)
                    self.assertEqual(fake_provider.analyze.call_count, 2)
                    fake_provider.analyze.side_effect = lambda *args: {
                        "stem": [], "options": [], "subquestions": [],
                        "uncertainties": [], "suspected_answer_leak": False,
                    }
                    response, error = json_request(connection, "POST", endpoint, {
                        "ids": ["q-selected"], "revision": replaced["revision"],
                        "replace_existing": True,
                    }, cookie)
                    self.assertEqual(response.status, 400, error)
                    self.assertIn("invalid type", error["error"])
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
