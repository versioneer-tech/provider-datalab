#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Install reviewed tools after checking their fixed archive checksums."""

import argparse
import hashlib
import json
import platform
import re
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path


def install(name, spec, destination):
    if "module" in spec:
        result = subprocess.run(["go", "mod", "download", "-json", spec["module"] + "@" + spec["version"]],
                                capture_output=True, text=True, check=True)
        if json.loads(result.stdout)["Sum"] != spec["module_sum"]:
            raise ValueError(f"{name}: Go module checksum does not match")
        destination.mkdir(parents=True, exist_ok=True)
        subprocess.run(["env", "GOBIN=" + str(destination.resolve()), "GOTOOLCHAIN=local", "go", "install",
                        spec["command"] + "@" + spec["version"]], check=True)
        print(f"Installed {name} {spec['version']}")
        return
    if not re.fullmatch(r"[0-9a-f]{64}", spec["sha256"]):
        raise ValueError(f"{name}: missing fixed SHA-256")
    with tempfile.TemporaryDirectory(prefix="datalab-tool-") as temporary:
        archive = Path(temporary) / "download"
        with urllib.request.urlopen(spec["url"], timeout=60) as response:
            archive.write_bytes(response.read())
        with archive.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != spec["sha256"]:
            raise ValueError(f"{name}: download checksum does not match")
        if "member" in spec:
            with tarfile.open(archive) as bundle:
                member = bundle.getmember(spec["member"])
                if not member.isfile():
                    raise ValueError(f"{name}: archive member is not a file")
                with bundle.extractfile(member) as source:
                    data = source.read()
        else:
            data = archive.read_bytes()
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / name
        target.write_bytes(data)
        target.chmod(0o755)
        print(f"Installed {name} {spec['version']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tools", nargs="+")
    parser.add_argument("--directory", type=Path, default=Path("build/tools"))
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ("Linux", "x86_64"):
        parser.error("The fixed tool archives support Linux AMD64 only.")
    specs = json.loads(Path(__file__).with_name("tools.json").read_text())
    for name in args.tools:
        install(name, specs[name], args.directory)


if __name__ == "__main__":
    main()
