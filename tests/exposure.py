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
    observed = list(yaml.safe_load_all(Path("tests/observed/001-lab.yaml").read_text()))

    def oauth_observer(secret):
        return {
            "apiVersion": "kubernetes.m.crossplane.io/v1alpha1", "kind": "Object",
            "metadata": {"name": "observe-oauth-client-secret-s-joe", "annotations": {
                "crossplane.io/composition-resource-name": "observe-oauth-client-secret-s-joe"}},
            "status": {"atProvider": {"manifest": {"data": {
                "clientSecret": base64.b64encode(secret.encode()).decode()}}}},
        }

    for exposure in ("ingress", "gateway", "gateway-s3", "disabled-data", "internal"):
        env = environment()
        if exposure in ("ingress", "internal"):
            env["data"]["httpRoute"].update(enabled=False, enableS3=False)
            env["data"]["ingress"].update(enabled=exposure == "ingress", **{"class": "nginx", "secret": "wildcard-tls"})
        if exposure == "gateway":
            env["data"]["httpRoute"].pop("enableS3")
        if exposure == "disabled-data":
            env["data"]["defaults"] = {"data": {"enabled": False}}
        env["data"].setdefault("defaults", {})["registry"] = {"enabled": False}
        if exposure == "ingress":
            env["data"]["ingress"]["annotations"] = {
                "nginx.ingress.kubernetes.io/proxy-body-size": "0",
                "nginx.ingress.kubernetes.io/proxy-buffering": "off",
                "nginx.ingress.kubernetes.io/proxy-request-buffering": "off",
            }
        if exposure == "gateway-s3":
            env["data"]["httpRoute"]["timeouts"] = {"request": "2h", "backendRequest": "1h30m"}
            env["data"]["oauth2Proxy"] = {"upstreamTimeout": "90m"}
        resources = render(args, env, observed=observed + [oauth_observer("initial-client-secret")])
        assert ("oauth2-client-secret-s-joe" in resources) == (
            exposure in ("ingress", "gateway", "gateway-s3")
        )
        gateway = exposure in ("gateway", "gateway-s3")
        s3 = exposure == "gateway-s3"
        assert ("data-ingress-s-joe" in resources) == (exposure == "ingress")
        assert ("data-route-s-joe" in resources) == gateway
        assert ("data-redirect-s-joe" in resources) == gateway
        if exposure == "ingress":
            assert manifest(resources, "data-ingress-s-joe")["metadata"]["annotations"] == env["data"]["ingress"]["annotations"]
        if gateway:
            route = manifest(resources, "data-route-s-joe")
            assert route["kind"] == "HTTPRoute"
            assert route["spec"]["hostnames"] == ["s-joe.lab.acme.com"]
            backends = {backend["name"]: backend["port"] for rule in route["spec"]["rules"]
                        for backend in rule["backendRefs"]}
            assert backends == ({"package-r": 4180, "data-s3": 8080} if s3 else {"package-r": 4180})
            assert all(rule["timeouts"] == env["data"]["httpRoute"].get("timeouts", {
                "request": "3600s", "backendRequest": "3600s"}) for rule in route["spec"]["rules"])
            redirect = manifest(resources, "data-redirect-s-joe")
            assert redirect["spec"]["rules"][0]["filters"][0]["requestRedirect"]["scheme"] == "https"
        for kind in ("config", "deployment", "service", "networkpolicy"):
            assert (f"data-s3-{kind}-s-joe" in resources) == s3
        assert any(item["metadata"]["name"] == "s-joe-s-joe-audience" for item in resources.values())
        assert ("data-deployment-s-joe" in resources) == (exposure != "disabled-data")
        assert ("runtime-storage-secret-s-joe" in resources) == (exposure != "disabled-data")
        if "observe-runtime-storage-secret-s-joe" in resources:
            assert manifest(resources, "observe-runtime-storage-secret-s-joe")["metadata"]["name"] == "s-joe-storage"
        if exposure != "disabled-data":
            storage = manifest(resources, "runtime-storage-secret-s-joe")["data"]
            assert "aws-credentials" in storage
            assert all(key.startswith("AWS_") or key == "aws-credentials" for key in storage)
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
                assert "--upstream-timeout=90m" in container_args
        if exposure in ("ingress", "gateway"):
            containers = manifest(resources, "data-deployment-s-joe")["spec"]["template"]["spec"]["containers"]
            assert "--upstream-timeout=3600s" in next(c["args"] for c in containers if c["name"] == "oauth2-proxy")
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
    generated = resources["connection-s-joe-s3"]["stringData"]
    assert generated["AWS_S3_FORCE_PATH_STYLE"] == "false"
    containers = manifest(resources, "data-s3-deployment-s-joe")["spec"]["template"]["spec"]["containers"]
    assert any(entry == {"name": "RCLONE_CONFIG_UPSTREAM_FORCE_PATH_STYLE", "value": "false"}
               for container in containers for entry in container.get("env", []))
    print("PASS custom IAM namespace and storage path style", flush=True)

    outputs = []
    for secret in ("initial-client-secret", "rotated-client-secret"):
        resources = render(args, environment(), observed=observed + [oauth_observer(secret)])
        projected = manifest(resources, "oauth2-client-secret-s-joe")
        assert "stringData" not in projected
        assert {key: base64.b64decode(value).decode() for key, value in projected["data"].items()} == {
            "client_id": "s-joe", "client_secret": secret,
            "cookie_secret": hashlib.sha256(secret.encode()).hexdigest()[:32],
        }
        generated = resources["connection-s-joe-s3"]["stringData"]
        assert not any(key.startswith("OAUTH2_") for key in generated)
        assert "secret-s-joe-datalab" not in resources
        assert "[default]" in generated["aws-credentials"]
        outputs.append(resources)
    for name in ("data-deployment-s-joe", "data-s3-deployment-s-joe"):
        checksums = [manifest(output, name)["spec"]["template"]["metadata"]["annotations"][
            "datalabs.versioneer.at/oauth2-cookie-checksum"] for output in outputs]
        assert checksums[0] != checksums[1]
    print("PASS OAuth credential projection and rotation", flush=True)

    pending = render(args, environment(), observed=[oauth_observer("initial-client-secret")])
    assert "oauth2-client-secret-s-joe" in pending
    disabled_env = environment()
    disabled_env["data"]["defaults"] = {"data": {"enabled": False}}
    disabled = render(args, disabled_env, observed=observed + [
        oauth_observer("initial-client-secret"), outputs[0]["oauth2-client-secret-s-joe"],
    ])
    assert "oauth2-client-secret-s-joe" not in disabled
    assert "observe-oauth-client-secret-s-joe" in disabled
    assert disabled["keycloak-client-s-joe"]["spec"]["writeConnectionSecretToRef"]["name"] == "s-joe-oauth-client"
    print("PASS runtime OAuth credentials use the service namespace and are removed with the proxy", flush=True)

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

    for request, backend, error in (
        ("10s", "11s", "backendRequest must not exceed request"),
        ("-1s", "1s", "httpRoute.timeouts.request must be a duration"),
        ("1h", "invalid", "httpRoute.timeouts.backendRequest must be a duration"),
    ):
        env = environment()
        env["data"]["httpRoute"]["timeouts"] = {"request": request, "backendRequest": backend}
        render(args, env, error=error)
    env = environment()
    env["data"]["oauth2Proxy"] = {"upstreamTimeout": "invalid"}
    render(args, env, error="oauth2Proxy.upstreamTimeout must be a duration")
    for request in ("10m", "0s"):
        env = environment()
        env["data"]["httpRoute"]["timeouts"] = {"request": request}
        env["data"]["oauth2Proxy"] = {"upstreamTimeout": "0s"}
        resources = render(args, env)
        assert all(rule["timeouts"] == {"request": request, "backendRequest": request}
                   for rule in manifest(resources, "data-route-s-joe")["spec"]["rules"])
        containers = manifest(resources, "data-deployment-s-joe")["spec"]["template"]["spec"]["containers"]
        assert "--upstream-timeout=0s" in next(c["args"] for c in containers if c["name"] == "oauth2-proxy")
    print("PASS transfer deadlines apply to browser and S3 routes, inherit request limits, and preserve zero", flush=True)


if __name__ == "__main__":
    main()
