#!/usr/bin/env python3
"""Run the local Kaoyan Question Builder web application."""

from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import mimetypes
import secrets
import shutil
import socket
import sys
import traceback
from http.cookies import CookieError, SimpleCookie
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
SHARED_ROOT = REPO_ROOT / "shared"
for path in (SCRIPT_DIR, SHARED_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from kaoyan.project_store import ProjectStore, RevisionConflict  # noqa: E402
from kaoyan.provider import ProviderConfig, ProviderError, VisionProvider  # noqa: E402
from question_builder.exporter import export_project  # noqa: E402
from question_builder.pdf_pipeline import (  # noqa: E402
    crop_region, detect_boundaries, merge_candidates, render_pdf, split_candidate,
)


STATIC_ROOT = SCRIPT_DIR.parent / "web"
STORE = ProjectStore(REPO_ROOT)
PROVIDER_CONFIG = ProviderConfig.from_environment()
SESSION_COOKIE = "kaoyan_qb_session"
SESSION_TOKEN = secrets.token_urlsafe(32)


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    value = host.rstrip(".").lower()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def loopback_bind_host(value: str) -> str:
    if value.rstrip(".").lower() == "localhost":
        return "127.0.0.1"
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("the question builder may only bind to a loopback address") from exc
    if not address.is_loopback:
        raise argparse.ArgumentTypeError("the question builder may only bind to a loopback address")
    return str(address)


def expected_revision(body: dict[str, Any]) -> int:
    revision = body.get("revision")
    if type(revision) is not int or revision < 1:
        raise ValueError("A positive integer project revision is required")
    return revision


def safe_static_path(name: str) -> Path:
    root = STATIC_ROOT.resolve()
    target = (root / name).resolve()
    if target == root or root not in target.parents:
        raise ValueError("Invalid static file path")
    return target


def json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length > 5_000_000:
        raise ValueError("JSON request is too large")
    value = json.loads(handler.rfile.read(length).decode("utf-8") or "{}")
    if not isinstance(value, dict):
        raise ValueError("JSON body must be an object")
    return value


def multipart_form(handler: BaseHTTPRequestHandler) -> tuple[dict[str, str], list[dict[str, Any]]]:
    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        raise ValueError("Upload must use multipart/form-data")
    length = int(handler.headers.get("Content-Length", "0"))
    if not 0 < length <= 500 * 1024 * 1024:
        raise ValueError("The total upload must be between 1 byte and 500 MB")
    message = BytesParser(policy=policy.default).parsebytes(
        ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode("ascii") + handler.rfile.read(length)
    )
    fields: dict[str, str] = {}
    uploads: list[dict[str, Any]] = []
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        if not name:
            continue
        if filename:
            uploads.append({"field": name, "filename": filename, "content": part.get_payload(decode=True) or b""})
        else:
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            try:
                fields[name] = payload.decode(charset).strip()
            except UnicodeDecodeError as exc:
                raise ValueError(f"Upload field {name} is not valid {charset} text") from exc
    return fields, uploads


def candidate(project: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    result = next((item for item in project.get("candidates", []) if item["id"] == candidate_id), None)
    if not result:
        raise ValueError("Candidate not found")
    return result


def validate_transcription_result(value: dict[str, Any]) -> dict[str, Any]:
    required_types = {
        "stem": str,
        "options": list,
        "subquestions": list,
        "uncertainties": list,
        "suspected_answer_leak": bool,
    }
    for field, expected_type in required_types.items():
        if field not in value or not isinstance(value[field], expected_type):
            raise ProviderError(f"Vision response field {field} has an invalid type")
    for field in ("options", "subquestions"):
        if any(not isinstance(item, (str, dict)) for item in value[field]):
            raise ProviderError(f"Vision response field {field} contains an invalid item")
    for uncertainty in value["uncertainties"]:
        if not isinstance(uncertainty, dict):
            raise ProviderError("Vision response uncertainty must be an object")
        confidence = uncertainty.get("confidence")
        if (
            not isinstance(uncertainty.get("fragment"), str)
            or not isinstance(uncertainty.get("reason"), str)
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise ProviderError("Vision response uncertainty is invalid")
    tables = value.setdefault("tables", [])
    if not isinstance(tables, list):
        raise ProviderError("Vision response tables must be an array")
    for table in tables:
        rows = table.get("rows") if isinstance(table, dict) else None
        headers = table.get("headers", []) if isinstance(table, dict) else None
        if not isinstance(rows, list) or not isinstance(headers, list):
            raise ProviderError("Vision response table is invalid")
        if any(not isinstance(row, list) or any(not isinstance(cell, str) for cell in row) for row in rows):
            raise ProviderError("Vision response table rows must contain strings")
        if any(not isinstance(cell, str) for cell in headers):
            raise ProviderError("Vision response table headers must contain strings")
    graphics = value.setdefault("graphics", [])
    if not isinstance(graphics, list) or any(
        not isinstance(box, list) or len(box) != 4 or any(isinstance(number, bool) or not isinstance(number, (int, float)) for number in box)
        or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)
        for box in graphics
    ):
        raise ProviderError("Vision response graphics must contain normalized boxes")
    if value.get("chapter") is not None and not isinstance(value.get("chapter"), str):
        raise ProviderError("Vision response chapter must be a string or null")
    return value


def safe_upload_name(name: str) -> str:
    value = Path(name).name
    if not value.lower().endswith(".pdf"):
        raise ValueError("Only PDF files are accepted")
    sanitized = "".join(char if char.isalnum() or char in ".-_() " else "_" for char in value)
    stem = sanitized[:-4].strip(" .") or "upload"
    return f"{stem[:156]}.pdf"


def unique_upload_name(name: str, used_names: set[str]) -> str:
    safe_name = safe_upload_name(name)
    stem = safe_name[:-4]
    candidate_name = safe_name
    suffix_number = 2
    while candidate_name.casefold() in used_names:
        suffix = f"-{suffix_number}.pdf"
        candidate_name = f"{stem[:160 - len(suffix)]}{suffix}"
        suffix_number += 1
    used_names.add(candidate_name.casefold())
    return candidate_name


class Handler(BaseHTTPRequestHandler):
    server_version = "KaoyanQuestionBuilder/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        # Do not log request bodies, API headers, source text, or file contents.
        sys.stderr.write(f"{self.address_string()} - {format % args}\n")

    def send_json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, attachment: bool = False, establish_session: bool = False) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        content = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if establish_session:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}={SESSION_TOKEN}; Path=/; HttpOnly; SameSite=Strict",
            )
        if attachment:
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(path.name)}")
        self.end_headers()
        self.wfile.write(content)

    def request_host(self) -> tuple[str, int] | None:
        authority = self.headers.get("Host", "")
        try:
            parsed = urlparse(f"//{authority}")
            port = parsed.port or self.server.server_port
        except ValueError:
            return None
        if (
            parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or not is_loopback_host(parsed.hostname)
            or port != self.server.server_port
        ):
            return None
        return parsed.hostname or "", port

    def has_session(self) -> bool:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return False
        value = cookie.get(SESSION_COOKIE)
        return bool(value and hmac.compare_digest(value.value, SESSION_TOKEN))

    def request_allowed(self, require_session: bool = False, state_changing: bool = False) -> bool:
        try:
            remote_is_loopback = ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            remote_is_loopback = False
        request_host = self.request_host()
        if not remote_is_loopback or request_host is None:
            self.send_json({"error": "The question builder only accepts loopback requests"}, HTTPStatus.FORBIDDEN)
            return False
        if require_session and not self.has_session():
            self.send_json({"error": "Open the question builder app before using its API"}, HTTPStatus.FORBIDDEN)
            return False
        origin = self.headers.get("Origin")
        if state_changing and origin:
            try:
                parsed = urlparse(origin)
                origin_port = parsed.port or (80 if parsed.scheme == "http" else 443)
            except ValueError:
                parsed, origin_port = None, None
            if (
                parsed is None
                or parsed.scheme != "http"
                or (parsed.hostname or "").rstrip(".").lower() != request_host[0].rstrip(".").lower()
                or origin_port != request_host[1]
            ):
                self.send_json({"error": "Cross-site requests are not allowed"}, HTTPStatus.FORBIDDEN)
                return False
        return True

    def do_GET(self) -> None:
        try:
            if not self.request_allowed():
                return
            parts = [unquote(item) for item in urlparse(self.path).path.split("/") if item]
            if not parts:
                self.send_file(STATIC_ROOT / "index.html", establish_session=True)
            elif parts[0] == "assets" and len(parts) == 2:
                self.send_file(safe_static_path(parts[1]))
            elif parts == ["api", "config"]:
                if self.request_allowed(require_session=True):
                    self.send_json(PROVIDER_CONFIG.public_dict())
            elif parts == ["api", "projects"]:
                if self.request_allowed(require_session=True):
                    self.send_json({"projects": STORE.list_projects()})
            elif len(parts) == 3 and parts[:2] == ["api", "projects"]:
                if self.request_allowed(require_session=True):
                    self.send_json(STORE.load(parts[2]))
            elif len(parts) >= 5 and parts[:2] == ["api", "projects"] and parts[3] == "files":
                if not self.request_allowed(require_session=True):
                    return
                folder = STORE.find_dir(parts[2]).resolve()
                relative = Path(*parts[4:])
                target = (folder / relative).resolve()
                if folder not in target.parents:
                    raise ValueError("Invalid file path")
                self.send_file(target, attachment=target.suffix.lower() == ".pdf" and "exports" in target.parts)
            elif len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3] == "crop":
                if not self.request_allowed(require_session=True):
                    return
                project = STORE.load(parts[2])
                item = candidate(project, parts[4])
                folder = STORE.find_dir(parts[2])
                output = folder / "crops" / f"{item['id']}.png"
                crop_region(folder / "pages" / f"page-{item['pdf_page']}.png", item["bbox"], output)
                self.send_file(output)
            else:
                self.send_error(404)
        except (ValueError, FileNotFoundError) as exc:
            self.send_json({"error": str(exc)}, 404)
        except Exception as exc:
            traceback.print_exc()
            self.send_json({"error": str(exc)}, 500)

    def do_POST(self) -> None:
        try:
            if not self.request_allowed(require_session=True, state_changing=True):
                return
            parts = [unquote(item) for item in urlparse(self.path).path.split("/") if item]
            if parts == ["api", "projects"]:
                self.create_project()
                return
            if len(parts) < 4 or parts[:2] != ["api", "projects"]:
                self.send_error(404)
                return
            project_id, action = parts[2], parts[3]
            body = json_body(self)
            revision = expected_revision(body)
            project = STORE.load(project_id, revision)
            if action == "merge":
                project["candidates"] = merge_candidates(project["candidates"], body.get("ids", []))
                STORE.write(project, "boundaries_merged", {"candidate_ids": body.get("ids", [])})
            elif action == "split":
                project["candidates"] = split_candidate(project["candidates"], body["candidate_id"], float(body.get("split_y", 0.5)))
                STORE.write(project, "boundary_split", {"candidate_id": body["candidate_id"]})
            elif action == "link":
                ids = body.get("ids", [])
                if len(ids) != 2:
                    raise ValueError("Choose exactly two candidates to link")
                first, second = candidate(project, ids[0]), candidate(project, ids[1])
                second.setdefault("relations", []).append({"type": body.get("type", "continuation_of"), "candidate_id": first["id"]})
                STORE.write(project, "cross_page_linked", {"ids": ids, "type": body.get("type", "continuation_of")})
            elif action == "recognize":
                if "provider" in body:
                    raise ValueError("Provider settings are fixed when the server starts")
                self.recognize(project, body)
                STORE.write(project, "selected_regions_recognized", {"candidate_ids": body.get("ids", [])})
            elif action == "export":
                if body.get("layout"):
                    allowed_layout = {"numbering", "answer_space_lines", "page_size", "print_profile"}
                    project.setdefault("layout", {}).update({key: value for key, value in body["layout"].items() if key in allowed_layout})
                result = export_project(REPO_ROOT, project, STORE.find_dir(project_id))
                project["last_export"] = result
                STORE.write(project, "pdf_exported", {"pages": result["pages"]})
                self.send_json({"project": project, "export": result})
                return
            elif action == "retention":
                self.send_json(STORE.authorize_retention(project_id, body["choice"], revision))
                return
            else:
                self.send_error(404)
                return
            self.send_json(project)
        except RevisionConflict as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
        except (ValueError, FileNotFoundError, FileExistsError, ProviderError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            traceback.print_exc()
            self.send_json({"error": str(exc)}, 500)

    def do_PATCH(self) -> None:
        try:
            if not self.request_allowed(require_session=True, state_changing=True):
                return
            parts = [unquote(item) for item in urlparse(self.path).path.split("/") if item]
            if len(parts) != 5 or parts[:2] != ["api", "projects"] or parts[3] != "candidates":
                self.send_error(404)
                return
            changes = json_body(self)
            revision = expected_revision(changes)
            changes.pop("revision")
            project = STORE.load(parts[2], revision)
            item = candidate(project, parts[4])
            allowed = {"selected", "order", "question_number", "book_page", "bbox", "preserve_graphics", "transcription", "answer_suspect"}
            unknown = set(changes) - allowed
            if unknown:
                raise ValueError(f"Unsupported candidate fields: {', '.join(sorted(unknown))}")
            if "bbox" in changes:
                x0, y0, x1, y1 = (float(value) for value in changes["bbox"])
                if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                    raise ValueError("Invalid normalized bbox")
                changes["bbox"] = [x0, y0, x1, y1]
            if "selected" in changes and type(changes["selected"]) is not bool:
                raise ValueError("selected must be a boolean")
            item.update(changes)
            STORE.write(project, "candidate_corrected", {"candidate_id": item["id"], "fields": sorted(changes)})
            self.send_json(project)
        except RevisionConflict as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
        except (ValueError, FileNotFoundError) as exc:
            self.send_json({"error": str(exc)}, 400)

    def create_project(self) -> None:
        fields, uploads = multipart_form(self)
        uploads = [upload for upload in uploads if upload["field"] == "pdf" and upload["filename"]]
        if not uploads:
            raise ValueError("Choose at least one PDF")
        project = STORE.create({
            "title": fields.get("title", "题目选编"), "subject": fields.get("subject", "考研题目"),
            "chapter": "按原资料顺序", "source_pdfs": [], "pages": [], "candidates": [],
            "layout": {"numbering": "preserve", "answer_space_lines": 5, "page_size": "A4", "print_profile": "bw"},
        })
        folder = STORE.find_dir(project["project_id"])
        try:
            used_names: set[str] = set()
            for upload in uploads:
                name = unique_upload_name(upload["filename"], used_names)
                stored = folder / "sources" / name
                stored.parent.mkdir(parents=True, exist_ok=True)
                stored.write_bytes(upload["content"])
                if stored.stat().st_size > 150 * 1024 * 1024:
                    raise ValueError(f"PDF is too large: {name}")
                source_index = len(project["source_pdfs"])
                pages = render_pdf(stored, folder / "pages" / f"source-{source_index}")
                detected, meta = detect_boundaries(stored)
                # Keep a flat page folder for the current single/multi-source UI while retaining source identity.
                page_offset = len(project["pages"])
                for page in pages:
                    original = folder / "pages" / f"source-{source_index}" / Path(page["image"]).name
                    flat_page = page_offset + page["pdf_page"]
                    flat = folder / "pages" / f"page-{flat_page}.png"
                    shutil.copy2(original, flat)
                    page.update({"flat_page": flat_page, "source_file": name, "image": f"pages/page-{flat_page}.png"})
                for item in detected:
                    item["source_pdf_page"] = item["pdf_page"]
                    item["pdf_page"] += page_offset
                    item["order"] += len(project["candidates"])
                for item in meta:
                    item["flat_page"] = item["pdf_page"] + page_offset
                project["source_pdfs"].append({"name": name, "stored_path": f"sources/{name}", "page_count": len(pages), "pages": meta})
                project["pages"].extend(pages)
                project["candidates"].extend(detected)
            STORE.write(project, "pdf_boundaries_detected", {"source_count": len(uploads), "candidate_count": len(project["candidates"])})
            self.send_json(project, HTTPStatus.CREATED)
        except Exception:
            STORE.authorize_retention(project["project_id"], "discard_all")
            raise

    def recognize(self, project: dict[str, Any], body: dict[str, Any]) -> None:
        requested_ids = body.get("ids")
        if requested_ids is None:
            ids = [item["id"] for item in project["candidates"] if item.get("selected")]
        elif not isinstance(requested_ids, list) or not all(isinstance(value, str) for value in requested_ids):
            raise ValueError("ids must be an array of candidate IDs")
        else:
            ids = list(dict.fromkeys(requested_ids))
        if not ids:
            raise ValueError("Choose at least one selected candidate to recognize")

        items = [candidate(project, candidate_id) for candidate_id in ids]
        if any(item.get("selected") is not True for item in items):
            raise ValueError("Recognition is limited to selected candidates")
        existing = [item["id"] for item in items if "transcription" in item and item["transcription"] is not None]
        if existing and body.get("replace_existing") is not True:
            raise ValueError("Existing transcription requires replace_existing=true")

        provider = VisionProvider(PROVIDER_CONFIG)
        folder = STORE.find_dir(project["project_id"])
        for item in items:
            crop = crop_region(folder / "pages" / f"page-{item['pdf_page']}.png", item["bbox"], folder / "crops" / f"{item['id']}.png", padding=10)
            prompt = (
                "Transcribe this selected exam-question region. Output JSON with keys: stem (string), options (array), "
                "subquestions (array), tables (array of {headers,rows} for simple tables), "
                "uncertainties (array of {fragment,reason,confidence}), suspected_answer_leak (boolean), "
                "graphics (array of normalized [x0,y0,x1,y1] boxes for geometry/function/statistics/complex data figures only), "
                "and chapter (string or null). Retype ordinary text, formulas and simple tables. Do not transcribe answers as question text."
            )
            result = validate_transcription_result(provider.analyze([crop], prompt, "high-precision-question-v1"))
            result.setdefault("uncertainties_confirmed", not bool(result.get("uncertainties")))
            result.setdefault("answer_leak_reviewed", not bool(result.get("suspected_answer_leak") or item.get("answer_suspect")))
            result.setdefault("subquestions_confirmed", len(result.get("subquestions", [])) >= int(item.get("subquestions_detected") or 0))
            item["transcription"] = result
            if result.get("graphics"):
                x0, y0, x1, y1 = item["bbox"]
                width, height = x1 - x0, y1 - y0
                item["preserve_graphics"] = [
                    [x0 + box[0] * width, y0 + box[1] * height, x0 + box[2] * width, y0 + box[3] * height]
                    for box in result["graphics"]
                    if len(box) == 4 and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1
                ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=loopback_bind_host, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server_class = ThreadingHTTPServer
    if ipaddress.ip_address(args.host).version == 6:
        class IPv6ThreadingHTTPServer(ThreadingHTTPServer):
            address_family = socket.AF_INET6

        server_class = IPv6ThreadingHTTPServer
    server = server_class((args.host, args.port), Handler)
    display_host = f"[{args.host}]" if ":" in args.host else args.host
    print(f"Kaoyan Question Builder: http://{display_host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
