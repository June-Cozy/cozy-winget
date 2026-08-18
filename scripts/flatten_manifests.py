#!/usr/bin/env python3
import argparse
import json
import os
import logging
import inspect
import sys
import yaml

try:
    from packaging.version import Version, InvalidVersion
except ImportError:
    Version = None
    InvalidVersion = Exception


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
    use_color = handler.stream.isatty()
    if use_color:
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


def _logger():
    _cname = inspect.stack()[1].function
    log = logging.getLogger(_cname)
    log.propagate = True
    return log


def _version_key(version_str):
    if Version is not None:
        try:
            return (0, Version(version_str))
        except InvalidVersion:
            pass
    parts = []
    for chunk in version_str.replace("-", ".").split("."):
        try:
            parts.append((0, int(chunk)))
        except ValueError:
            parts.append((1, chunk))
    return (1, tuple(parts))


def _load_yaml(path):
    log = _logger()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        log.warning(f"failed to parse {path}: {e}")
        return None


def collect_installer_files(manifests_root):
    for dirpath, _dirnames, filenames in os.walk(manifests_root):
        for name in filenames:
            if name.endswith(".installer.yaml"):
                yield os.path.join(dirpath, name)


def flatten(manifests_root):
    log = _logger()
    best = {}
    total = 0
    for path in collect_installer_files(manifests_root):
        total += 1
        doc = _load_yaml(path)
        if not doc:
            continue
        package_id = doc.get("PackageIdentifier")
        package_version = doc.get("PackageVersion")
        if not package_id or package_version is None:
            continue
        package_version = str(package_version)

        key = _version_key(package_version)
        existing = best.get(package_id)
        if existing is None or key > existing["_key"]:
            best[package_id] = {"_key": key, "doc": doc}
            log.debug(f"{package_id}")
        if total % 5000 == 0:
            log.info(f"...processed {total} installer manifests")
    log.info(f"done: {total} installer manifests, {len(best)} unique packages")
    return {package_id: data["doc"] for package_id, data in best.items()}


def main():
    parser = argparse.ArgumentParser(description="Flatten winget-pkgs manifests into a JSON index.")
    parser.add_argument("manifests_root", help="Path to the winget-pkgs manifests/ directory")
    parser.add_argument("-o", "--output", default="manifest.json", help="Output JSON path")
    parser.add_argument("--debug", action="store_true", help="Debug logging")
    args = parser.parse_args()

    _setup_logging(args.debug)
    log = _logger()

    result = flatten(args.manifests_root)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, sort_keys=True, default=str)
        f.write("\n")
    log.info(f"wrote {args.output}")


if __name__ == "__main__":
    main()
