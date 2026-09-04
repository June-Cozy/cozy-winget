#!/usr/bin/env python3
import argparse
import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[2;37m",
        logging.INFO: "\033[36m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[1;31m",
    }
    RESET = "\033[0m"
    DIM = "\033[2m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, "")
        levelname = f"{color}{record.levelname:<7}{self.RESET}"
        name = f"{self.DIM}{record.name}{self.RESET}"
        ts = self.formatTime(record, "%H:%M:%S")
        msg = record.getMessage()
        return f"{self.DIM}{ts}{self.RESET} {levelname} {name} {msg}"


def _setup_logging(debug=False):
    handler = logging.StreamHandler(sys.stderr)
    if handler.stream.isatty():
        handler.setFormatter(ColorFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
        ))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)


log = logging.getLogger("serve_manifest")


class ManifestStore:
    def __init__(self, path, watch=False):
        self.path = path
        self.watch = watch
        self._lock = threading.RLock()
        self._data = {}
        self._mtime = 0
        self._load()
        if watch:
            t = threading.Thread(target=self._watch_loop, daemon=True)
            t.start()

    def _load(self):
        start = time.monotonic()
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        with self._lock:
            self._data = data
            self._mtime = os.path.getmtime(self.path)
        log.info(f"loaded {len(data)} packages from {self.path} in {time.monotonic() - start:.2f}s")

    def _watch_loop(self):
        while True:
            time.sleep(5)
            try:
                mtime = os.path.getmtime(self.path)
                if mtime != self._mtime:
                    log.info("manifest file changed, reloading")
                    self._load()
            except OSError as e:
                log.warning(f"watch check failed: {e}")

    def get(self, package_id):
        with self._lock:
            return self._data.get(package_id)

    def search(self, query, limit=25):
        q = query.lower()
        with self._lock:
            items = list(self._data.items())
        matches = []
        for package_id, doc in items:
            if q in package_id.lower():
                matches.append(package_id)
                if len(matches) >= limit:
                    break
        return matches

    def summarize(self, package_id):
        doc = self.get(package_id)
        if doc is None:
            return None
        installers = doc.get("Installers") or [{}]
        arches = sorted({i.get("Architecture") for i in installers if i.get("Architecture")})
        types = sorted({i.get("InstallerType") or doc.get("InstallerType") for i in installers} - {None})
        return {
            "PackageIdentifier": doc.get("PackageIdentifier"),
            "PackageVersion": doc.get("PackageVersion"),
            "Architectures": arches,
            "InstallerTypes": types,
        }

    def scope_info(self, package_id):
        doc = self.get(package_id)
        if doc is None:
            return None
        top_scope = doc.get("Scope")
        installers = doc.get("Installers") or []
        effective = sorted({str(i.get("Scope") or top_scope) for i in installers}) or ["None"]
        return {
            "PackageIdentifier": doc.get("PackageIdentifier"),
            "Scopes": effective,
            "SupportsMachine": "machine" in effective,
        }

    def scope_info_bulk(self, package_ids):
        results = {}
        for pid in package_ids:
            info = self.scope_info(pid)
            results[pid] = info if info is not None else {"error": "not found"}
        return results


class Handler(BaseHTTPRequestHandler):
    store = None

    def log_message(self, fmt, *args):
        log.debug(f"{self.client_address[0]} {fmt % args}")

    def _json(self, status, payload):
        body = json.dumps(payload, indent=1, sort_keys=True, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        qs = parse_qs(parsed.query)

        if not parts or parts[0] != "v1":
            self._json(404, {"error": "not found, try /v1/..."})
            return

        rest = parts[1:]

        if rest == ["health"]:
            self._json(200, {"status": "ok"})
            return

        if len(rest) == 2 and rest[0] == "pkg":
            package_id = rest[1]
            doc = self.store.get(package_id)
            if doc is None:
                self._json(404, {"error": f"no such package: {package_id}"})
                return
            self._json(200, doc)
            return

        if rest == ["scopes"]:
            ids_raw = (qs.get("ids") or [""])[0]
            package_ids = [p for p in ids_raw.split(",") if p]
            if not package_ids:
                self._json(400, {"error": "missing ids param (comma-separated)"})
                return
            self._json(200, self.store.scope_info_bulk(package_ids))
            return

        if rest == ["search"]:
            query = (qs.get("q") or [""])[0]
            if not query:
                self._json(400, {"error": "missing q param"})
                return
            full = (qs.get("full") or ["0"])[0] in ("1", "true", "yes")
            limit_raw = (qs.get("limit") or ["25"])[0]
            try:
                limit = max(1, min(200, int(limit_raw)))
            except ValueError:
                limit = 25
            matches = self.store.search(query, limit=limit)
            if full:
                results = [self.store.get(pid) for pid in matches]
            else:
                results = [self.store.summarize(pid) for pid in matches]
            self._json(200, {"query": query, "count": len(results), "results": results})
            return

        self._json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]

        if len(parts) == 2 and parts[0] == "v1" and parts[1] == "scopes":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(body) if body else {}
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid json body"})
                return
            package_ids = payload.get("ids") or []
            if not isinstance(package_ids, list) or not package_ids:
                self._json(400, {"error": "expected {\"ids\": [...]}"})
                return
            self._json(200, self.store.scope_info_bulk(package_ids))
            return

        self._json(404, {"error": "not found"})


def main():
    parser = argparse.ArgumentParser(description="Serve flattened winget manifest.jsonl over HTTP.")
    parser.add_argument("manifest", help="Path to manifest.jsonl")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--watch", action="store_true", help="Reload manifest.jsonl if it changes on disk")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    _setup_logging(args.debug)

    store = ManifestStore(args.manifest, watch=args.watch)
    Handler.store = store

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    log.info(f"serving on http://{args.host}:{args.port} (v1)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
