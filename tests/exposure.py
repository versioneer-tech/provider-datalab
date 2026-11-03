# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check Data endpoints, credential projection, and invalid exposure settings."""

import base64
import hashlib
from pathlib import Path

import yaml

from render import arguments, environment, manifest, render


def main():
    args = arguments()
    for exposure in ("ingress", "gateway", "gateway-s3", "disabled-data", "internal"):
        env = environment()
        if exposure in ("ingress", "internal"):
            env["data"]["httpRoute"].update(enabled=False, enableS3=False)
            env["data"]["ingress"].update(enabled=exposure == "ingress", **{"class": "nginx", "secret": "wildcard-tls"})
        if exposure == "gateway":
            env["data"]["httpRoute"].pop("enableS3")
        if exposure == "disabled-data":
            env["data"]["defaults"] = {"data": {"enabled": False}}
        resources = render(args, env)
        gateway = exposure in ("gateway", "gateway-s3")
        s3 = exposure == "gateway-s3"
        assert ("data-ingress-s-joe" in resources) == (exposure == "ingress")
        assert ("data-route-s-joe" in resources) == gateway
        assert ("data-redirect-s-joe" in resources) == gateway
        if gateway:
            route = manifest(resources, "data-route-s-joe")
            assert route["kind"] == "HTTPRoute"
            assert route["spec"]["hostnames"] == ["s-joe.lab.acme.com"]
            backends = {backend["name"]: backend["port"] for rule in route["spec"]["rules"]
                        for backend in rule["backendRefs"]}
            assert backends == ({"package-r": 4180, "data-s3": 8080} if s3 else {"package-r": 4180})
            redirect = manifest(resources, "data-redirect-s-joe")
            assert redirect["spec"]["rules"][0]["filters"][0]["requestRedirect"]["scheme"] == "https"
        for kind in ("config", "deployment", "service", "networkpolicy"):
            assert (f"data-s3-{kind}-s-joe" in resources) == s3
        assert any(item["metadata"]["name"] == "s-joe-s-joe-audience" for item in resources.values()) == s3
        assert ("data-deployment-s-joe" in resources) == (exposure != "disabled-data")
        if s3:
            for name in ("data-deployment-s-joe", "data-s3-deployment-s-joe"):
                pod = manifest(resources, name)["spec"]["template"]["spec"]
                containers = pod["containers"]
                names = {entry["name"] for container in containers for entry in container.get("env", [])}
                assert "AWS_SHARED_CREDENTIALS_FILE" in names
                assert names.isdisjoint({"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                                         "OAUTH2_PROXY_CLIENT_SECRET", "OAUTH2_PROXY_COOKIE_SECRET"})
                mounts = [mount for container in containers for mount in container.get("volumeMounts", [])]
                assert any(mount["name"] == "oauth2-credentials" for mount in mounts)
                assert all("subPath" not in mount for mount in mounts if mount["name"] == "oauth2-credentials")
                container_args = [arg for container in containers for arg in container.get("args", [])]
                assert "--client-secret-file=/var/run/datalab/oauth2/client_secret" in container_args
                assert "--cookie-secret-file=/var/run/datalab/oauth2/cookie_secret" in container_args
        print(f"PASS Data exposure: {exposure}", flush=True)

    env = environment()
    env["data"]["iam"]["namespace"] = "identity"
    env["data"]["storage"] = {"forcePathStyle": False}
    resources = render(args, env)
    policy = manifest(resources, "data-s3-networkpolicy-s-joe")["spec"]
    destinations = [target for rule in policy["egress"] for target in rule.get("to", [])]
    assert any(target.get("namespaceSelector", {}).get("matchLabels", {}).get("kubernetes.io/metadata.name") == "identity"
               for target in destinations)
    assert "Egress" in policy["policyTypes"]
    assert any(port["port"] == 8080 for rule in policy["egress"] for port in rule.get("ports", []))
    generated = resources["secret-s-joe-datalab"]["stringData"]
    assert generated["AWS_S3_FORCE_PATH_STYLE"] == "false"
    containers = manifest(resources, "data-s3-deployment-s-joe")["spec"]["template"]["spec"]["containers"]
    assert any(entry == {"name": "RCLONE_CONFIG_UPSTREAM_FORCE_PATH_STYLE", "value": "false"}
               for container in containers for entry in container.get("env", []))
    print("PASS custom IAM namespace and storage path style", flush=True)

    observed = list(yaml.safe_load_all(Path("tests/observed/001-lab.yaml").read_text()))
    outputs = []
    for secret in ("initial-client-secret", "rotated-client-secret"):
        observer = {
            "apiVersion": "kubernetes.m.crossplane.io/v1alpha1", "kind": "Object",
            "metadata": {"name": "observe-oauth-client-secret-s-joe", "annotations": {
                "crossplane.io/composition-resource-name": "observe-oauth-client-secret-s-joe"}},
            "status": {"atProvider": {"manifest": {"data": {
                "clientSecret": base64.b64encode(secret.encode()).decode()}}}},
        }
        resources = render(args, environment(), observed=observed + [observer])
        projected = manifest(resources, "oauth2-client-secret-s-joe")
        assert "stringData" not in projected
        assert {key: base64.b64decode(value).decode() for key, value in projected["data"].items()} == {
            "client_id": "s-joe", "client_secret": secret,
            "cookie_secret": hashlib.sha256(secret.encode()).hexdigest()[:32],
        }
        generated = resources["secret-s-joe-datalab"]["stringData"]
        assert generated["OAUTH2_CLIENT_ID"] == "s-joe"
        assert generated["OAUTH2_CLIENT_SECRET"] == secret
        assert "[default]" in generated["aws-credentials"]
        outputs.append(resources)
    for name in ("data-deployment-s-joe", "data-s3-deployment-s-joe"):
        checksums = [manifest(output, name)["spec"]["template"]["metadata"]["annotations"][
            "datalabs.pkg.internal/oauth2-cookie-checksum"] for output in outputs]
        assert checksums[0] != checksums[1]
    print("PASS OAuth credential projection and rotation", flush=True)

    for path, value, error in (
        (("ingress", "enabled"), True, "Enable only one"),
        (("httpRoute", "enabled"), False, "enableS3 requires"),
        (("httpRoute", "parentName"), None, "httpRoute.parentName"),
    ):
        env = environment()
        if value is None:
            env["data"][path[0]].pop(path[1])
        else:
            env["data"][path[0]][path[1]] = value
        render(args, env, error=error)
    env = environment()
    env["data"]["ingress"].update(enabled=True, **{"class": "nginx"})
    env["data"]["httpRoute"].update(enabled=False, enableS3=False)
    render(args, env, error="ingress.secret")
    print("PASS invalid exposure settings rejected", flush=True)


if __name__ == "__main__":
    main()
