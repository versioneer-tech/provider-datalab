# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check registry storage, authentication, routes, and connection publication."""

import base64
from copy import deepcopy
import json

from render import arguments, environment, manifest, render


def encoded(values):
    return {key: base64.b64encode(value.encode()).decode() for key, value in values.items()}


def main():
    args = arguments()
    env = environment()
    env["data"]["defaults"] = {"data": {"enabled": False}, "registry": {"enabled": True}, "security": {"externalEgress": False}}
    env["data"]["storage"] = {"region": "us-east-1", "forcePathStyle": True}
    source = {"apiVersion": "versioneer.at/v1", "kind": "Datalab",
              "metadata": {"name": "s-joe", "namespace": "teams"}, "spec": {}}

    def observer(key, body):
        return {"apiVersion": "kubernetes.m.crossplane.io/v1alpha1", "kind": "Object",
                "metadata": {"name": key, "namespace": "teams", "annotations": {
                    "crossplane.io/composition-resource-name": key}},
                "status": {"atProvider": {"manifest": body}, "conditions": [
                    {"type": "Ready", "status": "True"}, {"type": "Synced", "status": "True"}]}}

    storage = observer("observe-runtime-storage-secret-s-joe", {
        "apiVersion": "v1", "kind": "Secret", "metadata": {"name": "s-joe-storage", "namespace": "s-joe"},
        "data": encoded({"aws-credentials": "[default]\naws_access_key_id = test-access\naws_secret_access_key = test-secret\n",
                         "AWS_REGION": "us-east-1", "AWS_ENDPOINT_URL": "http://minio.storage:9000"}),
    })

    def run(config=env, observed=None):
        return render(args, config, source, [storage] if observed is None else observed, include_composite=True)

    def connection(resources):
        return next(c for c in resources["composite"]["status"]["connections"] if c["type"] == "registry")

    waiting = run(observed=[])
    assert "namespace-s-joe" in waiting
    assert "networkpolicy-s-joe-allow-dns-egress" in waiting
    assert "registry-auth-secret-s-joe" in waiting and "registry-deployment-s-joe" not in waiting
    resources = run()
    deployment = manifest(resources, "registry-deployment-s-joe")
    pod = deployment["spec"]["template"]
    container = pod["spec"]["containers"][0]
    assert container["image"] == "registry:3.1.2"
    config = json.loads(manifest(resources, "registry-config-s-joe")["data"]["config.yml"])
    assert config["storage"]["s3"]["bucket"] == "s-joe"
    assert "rootdirectory" not in config["storage"]["s3"]
    assert config["storage"]["s3"]["forcepathstyle"] and not config["storage"]["s3"]["secure"]
    assert "accesskey" not in config["storage"]["s3"] and "secretkey" not in config["storage"]["s3"]
    assert config["storage"]["redirect"]["disable"]
    assert config["auth"]["htpasswd"]["path"] == "/auth/htpasswd"
    variables = {entry["name"]: entry for entry in container["env"]}
    assert variables["AWS_SHARED_CREDENTIALS_FILE"]["value"] == "/var/run/datalab/storage/aws-credentials"
    assert variables["REGISTRY_STORAGE_S3_REGIONENDPOINT"]["value"] == "$(AWS_ENDPOINT_URL)"
    assert variables["AWS_ENDPOINT_URL"]["valueFrom"]["secretKeyRef"] == {"name": "s-joe-storage", "key": "AWS_ENDPOINT_URL"}
    assert "test-secret" not in json.dumps(deployment) + json.dumps(config)
    assert not any("persistentVolumeClaim" in volume for volume in pod["spec"]["volumes"])
    assert container["readinessProbe"]["httpGet"] == {"path": "/debug/health", "port": "health"}
    assert manifest(resources, "registry-service-s-joe")["spec"]["ports"][0]["port"] == 5000
    print("PASS shared S3 registry needs runtime credentials, not sessions, Data, or a registry PVC")

    route = manifest(resources, "registry-route-s-joe")["spec"]
    assert route["hostnames"] == ["s-joe.lab.acme.com"]
    assert [rule["matches"][0]["path"]["value"] for rule in route["rules"]] == ["/v2"]
    assert "filters" not in route["rules"][0]
    assert route["rules"][0]["timeouts"] == {"request": "3600s", "backendRequest": "3600s"}
    policy = manifest(resources, "registry-networkpolicy-s-joe")["spec"]
    assert policy["ingress"] == [{"ports": [{"protocol": "TCP", "port": 5000}]}]
    ingress_env = deepcopy(env)
    ingress_env["data"]["httpRoute"]["enabled"] = False
    ingress_env["data"]["httpRoute"]["enableS3"] = False
    ingress_env["data"]["defaults"]["data"]["enabled"] = True
    ingress_env["data"]["ingress"].update(enabled=True, **{"class": "nginx", "secret": "wildcard"})
    ingress_env["data"]["ingress"]["annotations"] = {
        "nginx.ingress.kubernetes.io/proxy-body-size": "2g",
        "nginx.ingress.kubernetes.io/proxy-read-timeout": "7200",
        "nginx.ingress.kubernetes.io/proxy-request-buffering": "on",
        "test.example/annotation": "custom",
    }
    ingress_resources = run(ingress_env)
    assert manifest(ingress_resources, "registry-ingress-s-joe")["spec"]["rules"][0]["http"]["paths"][0]["path"] == "/v2"
    assert "registry-prefix-ingress-s-joe" not in ingress_resources
    assert "nginx.ingress.kubernetes.io/rewrite-target" not in manifest(ingress_resources, "registry-ingress-s-joe")["metadata"]["annotations"]
    assert manifest(ingress_resources, "registry-ingress-s-joe")["metadata"]["annotations"] == ingress_env["data"]["ingress"]["annotations"]
    assert manifest(ingress_resources, "data-ingress-s-joe")["metadata"]["annotations"] == ingress_env["data"]["ingress"]["annotations"]
    print("PASS Gateway and Ingress route the native Docker API without rewriting paths or exposing health")

    custom = deepcopy(env)
    custom["data"]["httpRoute"]["timeouts"] = {"request": "0s", "backendRequest": "2h"}
    assert manifest(run(custom), "registry-route-s-joe")["spec"]["rules"][0]["timeouts"] == custom["data"]["httpRoute"]["timeouts"]
    custom["data"]["httpRoute"]["timeouts"] = {"request": "5m", "backendRequest": "10m"}
    render(args, custom, source, [storage], error="backendRequest must not exceed request")
    print("PASS registry-only exposure uses configured timeouts and rejects an invalid backend deadline")

    rotated = deepcopy(storage)
    rotated["status"]["atProvider"]["manifest"]["data"].update(encoded({
        "aws-credentials": "[default]\naws_access_key_id = rotated\naws_secret_access_key = rotated-secret\n",
        "AWS_ENDPOINT_URL": "https://s3.example", "AWS_REGION": "eu-west-1",
    }))
    changed = run(observed=[rotated])
    assert manifest(changed, "registry-deployment-s-joe")["spec"]["template"]["metadata"]["annotations"] != pod["metadata"]["annotations"]
    changed_config = json.loads(manifest(changed, "registry-config-s-joe")["data"]["config.yml"])
    assert changed_config["storage"]["s3"]["secure"] and changed_config["storage"]["s3"]["region"] == "eu-west-1"
    assert manifest(changed, "registry-auth-secret-s-joe") == manifest(resources, "registry-auth-secret-s-joe")
    print("PASS storage rotation restarts the registry and preserves its client credentials")

    auth = manifest(resources, "registry-auth-secret-s-joe")
    observed = [storage, observer("observe-registry-auth-secret-s-joe", auth)]
    pending = run(observed=observed)
    info = connection(pending)
    assert info["name"] == "primary" and info["endpoint"] == "https://s-joe.lab.acme.com/v2/" and not info["ready"]
    published = next(body for body in pending.values() if body.get("kind") == "Secret"
                     and body["metadata"]["name"] == info["secretRef"]["name"])
    assert published["metadata"]["namespace"] == info["secretRef"]["namespace"] == "teams"
    assert set(published["data"]) == {"user", "password"}
    for key in ("registry-deployment-s-joe", "registry-route-s-joe"):
        ready = deepcopy(resources[key])
        ready["status"] = {"conditions": [{"type": "Ready", "status": "True"}]}
        observed.append(ready)
    observed.append(published)
    assert connection(run(observed=observed))["ready"]
    observed[-1] = deepcopy(published)
    observed[-1]["data"]["password"] = encoded({"password": "stale"})["password"]
    assert not connection(run(observed=observed))["ready"]
    assert auth["data"]["password"] not in json.dumps(info)
    disabled = deepcopy(env)
    disabled["data"]["defaults"]["registry"]["enabled"] = False
    removed = run(disabled, observed)
    assert not any(key.startswith("registry-") for key in removed)
    assert not any(c["type"] == "registry" for c in removed["composite"]["status"]["connections"])
    print("PASS registry connections publish only user/password and wait for current credentials and workload readiness")
    print("PASS disabling the registry removes its resources and connection without deleting S3 data")


if __name__ == "__main__":
    main()
