#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Apply cluster network and storage settings to integration environments."""

import argparse
import ipaddress
from pathlib import Path
import sys

import yaml


def configure(documents, storage_class, service_cidr, pod_cidrs, control_plane_storage_class=None, snapshot_class=None):
    service_cidr = str(ipaddress.ip_network(service_cidr))
    pod_cidrs = [str(ipaddress.ip_network(cidr)) for cidr in pod_cidrs.split(",")]
    control_plane_storage_class = control_plane_storage_class or storage_class
    allowed_classes = list(dict.fromkeys([storage_class, control_plane_storage_class]))
    for document in documents:
        data = document["data"]
        data.setdefault("network", {}).update(serviceCIDR=service_cidr, podCIDRs=pod_cidrs)
        vcluster = data.setdefault("vcluster", {})
        vcluster["storageClassName"] = control_plane_storage_class
        data.setdefault("volumes", {})["storageClasses"] = {"allowed": allowed_classes, "default": storage_class}
        data.setdefault("database", {})["storageClassName"] = storage_class
        data.setdefault("cacheStore", {})["storageClassName"] = storage_class
        if snapshot_class:
            data["database"]["snapshotClassName"] = snapshot_class
            data["cacheStore"]["snapshotClassName"] = snapshot_class
    return documents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--storage-class", required=True)
    parser.add_argument("--control-plane-storage-class")
    parser.add_argument("--snapshot-class")
    parser.add_argument("--service-cidr", required=True)
    parser.add_argument("--pod-cidrs", required=True)
    args = parser.parse_args()
    documents = list(yaml.safe_load_all(args.manifest.read_text()))
    documents = configure(documents, args.storage_class, args.service_cidr, args.pod_cidrs,
                          args.control_plane_storage_class, args.snapshot_class)
    yaml.safe_dump_all(documents, sys.stdout)


if __name__ == "__main__":
    main()
