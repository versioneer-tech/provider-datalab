# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check S3 discovery settings and source precedence."""

import base64
from copy import deepcopy
import json

from render import arguments, environment, render


def main():
    args = arguments()
    env = environment()
    env["data"]["defaults"] = {"data": {"enabled": False}}
    env["data"]["storage"] = {"endpoint": "https://s3.acme.com", "region": "acme"}
    source = {
        "apiVersion": "pkg.internal/v1beta2", "kind": "Datalab",
        "metadata": {"name": "test-storage", "namespace": "workspace"},
        "spec": {"sessions": []},
    }
    observer = {
        "apiVersion": "kubernetes.m.crossplane.io/v1alpha1", "kind": "Object",
        "metadata": {"name": "observe-storage-secret-test-storage", "namespace": "workspace",
                     "annotations": {"crossplane.io/composition-resource-name": "observe-storage-secret-test-storage"}},
        "status": {
            "conditions": [{"type": "Ready", "status": "True"}],
            "atProvider": {"manifest": {
                "apiVersion": "v1", "kind": "Secret",
                "metadata": {"name": "test-storage", "namespace": "workspace"},
                "data": {key: base64.b64encode(value.encode()).decode() for key, value in {
                    "AWS_ENDPOINT_URL": "https://s3.custom.acme.com", "AWS_REGION": "custom-acme",
                    "AWS_ACCESS_KEY_ID": "test-access", "AWS_SECRET_ACCESS_KEY": "test-private",
                    "AWS_SESSION_TOKEN": "test-token",
                }.items()},
            }},
        },
    }
    expected = {"name": "primary", "type": "s3", "ready": True,
                "secretRef": {"name": "test-storage", "namespace": "workspace"}}

    def connection(config, observed):
        result = render(args, config, source, [observed], include_composite=True)["composite"]["status"]
        assert not any(value in json.dumps(result) for value in ("test-access", "test-private", "test-token"))
        return result["connections"]

    assert connection(env, observer) == [{**expected, "endpoint": "https://s3.custom.acme.com", "region": "custom-acme"}]
    fallback = deepcopy(observer)
    data = fallback["status"]["atProvider"]["manifest"]["data"]
    data.pop("AWS_ENDPOINT_URL")
    data["AWS_REGION"] = ""
    assert connection(env, fallback) == [{**expected, **env["data"]["storage"]}]
    env["data"]["storage"] = {}
    assert connection(env, fallback) == [expected]
    print("PASS S3 discovery uses source settings, falls back to environment settings, and omits missing values")


if __name__ == "__main__":
    main()
