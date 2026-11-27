#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Fetch checked platform inputs and pin their container images."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "scripts/components.json").read_text())


def image_pin(repository):
    matches = {value for value in LOCK["images"].values()
               if value.split("@")[0].rsplit(":", 1)[0] == repository}
    if len(matches) != 1:
        raise ValueError(f"One image pin is required for {repository}")
    return matches.pop()


def pin_images(value):
    if isinstance(value, str):
        return LOCK["images"].get(value, value)
    if isinstance(value, list):
        return [pin_images(item) for item in value]
    if isinstance(value, dict):
        result = {key: pin_images(item) for key, item in value.items()}
        args = result.get("args") or []
        if isinstance(args, list) and args[:1] == ["gateway-provisioner"]:
            # The provisioner creates these images after bootstrap.
            result["args"] = [arg for arg in args if not arg.startswith(("--contour-image=", "--envoy-image="))] + [
                "--contour-image=" + image_pin("ghcr.io/projectcontour/contour"),
                "--envoy-image=" + image_pin("docker.io/envoyproxy/envoy"),
            ]
        image = result.get("image")
        if isinstance(image, str) and image and not re.fullmatch(r"\S+@sha256:[0-9a-f]{64}", image):
            raise ValueError(f"Unpinned platform image: {image}")
        return result
    return value


def artifact(name):
    entry = LOCK["artifacts"][name]
    cache = ROOT / "build/components"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / entry["filename"]
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]:
        return path
    with urllib.request.urlopen(entry["url"], timeout=90) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError(f"Checksum mismatch for {name}")
    with tempfile.NamedTemporaryFile(dir=cache, delete=False) as temporary:
        temporary.write(data)
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", nargs="?", choices=sorted(LOCK["artifacts"]))
    parser.add_argument("--manifest", action="store_true")
    parser.add_argument("--image", help="Print the locked image reference for a repository")
    args = parser.parse_args()
    if args.image:
        if args.artifact or args.manifest:
            parser.error("--image cannot be combined with an artifact or --manifest")
        print(image_pin(args.image))
        return
    if args.artifact:
        path = artifact(args.artifact)
        if not args.manifest:
            print(path)
            return
        documents = yaml.safe_load_all(path.read_text())
    else:
        documents = yaml.safe_load_all(sys.stdin)
    checked = [pin_images(item) for item in documents if item is not None]
    yaml.safe_dump_all(checked, sys.stdout, sort_keys=False)


if __name__ == "__main__":
    main()
