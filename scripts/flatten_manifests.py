#!/usr/bin/env python3
import argparse
import json
import os
import sys

import yaml

try:
    from packaging.version import Version, InvalidVersion
except ImportError:
    Version = None
    InvalidVersion = Exception


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
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"warn: failed to parse {path}: {e}", file=sys.stderr)
        return None


def _collapse(values):
    if not values:
        return None
    if len(values) == 1:
        return next(iter(values))
    return sorted(values)


def _extract_field(installer_doc, field):
    if not installer_doc:
        return None
    top_value = installer_doc.get(field)
    installers = installer_doc.get("Installers") or []
    values = set()
    for entry in installers:
        if not isinstance(entry, dict):
            continue
        v = entry.get(field, top_value)
        if v:
            values.add(v)
    if not values and top_value:
        values.add(top_value)
    return _collapse(values)


def _extract_fields(installer_doc):
    scope = _extract_field(installer_doc, "Scope")
    installer_type = _extract_field(installer_doc, "InstallerType")
    elevation = _extract_field(installer_doc, "ElevationRequirement")
    return scope, installer_type, elevation


def collect_installer_files(manifests_root):
    for dirpath, _dirnames, filenames in os.walk(manifests_root):
        for name in filenames:
            if name.endswith(".installer.yaml"):
                yield os.path.join(dirpath, name)


def flatten(manifests_root):
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
        scope, installer_type, elevation = _extract_fields(doc)
        release_date = doc.get("ReleaseDate")
        if release_date is not None:
            release_date = str(release_date)

        key = _version_key(package_version)
        existing = best.get(package_id)
        if existing is None or key > existing["_key"]:
            best[package_id] = {
                "_key": key,
                "version": package_version,
                "scope": scope,
                "installerType": installer_type,
                "elevationRequirement": elevation,
                "releaseDate": release_date,
            }
        if total % 5000 == 0:
            print(f"...processed {total} installer manifests", file=sys.stderr)
    print(f"done: {total} installer manifests, {len(best)} unique packages", file=sys.stderr)
    result = {}
    for package_id, data in best.items():
        result[package_id] = {
            "version": data["version"],
            "scope": data["scope"],
            "installerType": data["installerType"],
            "elevationRequirement": data["elevationRequirement"],
            "releaseDate": data["releaseDate"],
        }
    return result


def main():
    parser = argparse.ArgumentParser(description="Flatten winget-pkgs manifests into a JSON index.")
    parser.add_argument("manifests_root", help="Path to the winget-pkgs manifests/ directory")
    parser.add_argument("-o", "--output", default="manifest.json", help="Output JSON path")
    args = parser.parse_args()

    result = flatten(args.manifests_root)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, sort_keys=True)
        f.write("\n")
    print(f"wrote {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
