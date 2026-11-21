#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Apply cluster network and storage settings to integration environments."""

import argparse
import ipaddress
from pathlib import Path
import sys

import yaml


def configure(documents, storage_class, service_cidr, pod_cidrs):
    service_cidr = str(ipaddress.ip_network(service_cidr))
    pod_cidrs = [str(ipaddress.ip_network(cidr)) for cidr in pod_cidrs.split(",")]
    for document in documents:
        data = document["data"]
        data.setdefault("network", {}).update(serviceCIDR=service_cidr, podCIDRs=pod_cidrs)
        vcluster = data.setdefault("vcluster", {})
        vcluster["storageClassName"] = storage_class
        data.setdefault("volumes", {})["storageClasses"] = {"allowed": [storage_class], "default": storage_class}
    return documents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--storage-class", required=True)
    parser.add_argument("--service-cidr", required=True)
    parser.add_argument("--pod-cidrs", required=True)
    args = parser.parse_args()
    documents = list(yaml.safe_load_all(args.manifest.read_text()))
    documents = configure(documents, args.storage_class, args.service_cidr, args.pod_cidrs)
    yaml.safe_dump_all(documents, sys.stdout)


if __name__ == "__main__":
    main()
