#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check HTTPS path routing, Datalab authorization, and persistent cluster state."""

import argparse
import base64
import http.client
import http.server
import json
import os
import secrets
from pathlib import Path
import select
import socket
import threading
import ssl
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ISSUER = "https://keycloak.keycloak:8443/realms/integration"
LAB = "verify-vcluster"
HOST = "verify-vcluster.lab.acme.com"
PREFIX = "/.vc0"


CATALOG_PATH = "/api/v1/namespaces/demo/services/catalog:8080/proxy"
COLLECTION = "verify-vcluster-catalog"


def wait_until(check, message, seconds=300):
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline, message
        time.sleep(3)


def check_catalog(api, bearer):
    result = api(
        CATALOG_PATH + "/search",
        bearer,
        {"collections": [COLLECTION], "bbox": [16, 47, 18, 49]},
        method="POST",
    )
    assert [item["id"] for item in result["features"]] == ["catalog-item"]
    assert result["features"][0]["collection"] == COLLECTION
    print(
        "PASS Datalab catalog item is searchable through the vcluster API", flush=True
    )


def deploy_catalog(api, bearer):
    postgres = Path("/postgres")
    values = {
        target: (postgres / source).read_text().strip()
        for target, source in (
            ("PGHOST", "POSTGRES_PG0_HOST"),
            ("PGPORT", "POSTGRES_PG0_PORT"),
            ("PGUSER", "POSTGRES_PG0_USER"),
            ("PGPASSWORD", "POSTGRES_PG0_PASSWORD"),
        )
    }
    values["PGDATABASE"] = "catalog"
    for name, data in (
        ("catalog-postgres-admin", values),
        (
            "catalog-postgres",
            {**values, "PGUSER": "catalog", "PGPASSWORD": secrets.token_urlsafe(32)},
        ),
    ):
        api(
            "/api/v1/namespaces/demo/secrets",
            bearer,
            method="POST",
            expected=201,
            body={
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": name},
                "stringData": data,
            },
        )
    documents = json.loads(Path("/test/catalog.json").read_text())
    api(
        "/apis/batch/v1/namespaces/demo/jobs",
        bearer,
        documents[0],
        method="POST",
        expected=201,
    )

    def migration_finished():
        status = api("/apis/batch/v1/namespaces/demo/jobs/catalog-migrate", bearer).get(
            "status", {}
        )
        assert not status.get("failed"), "PgSTAC migration Job failed"
        return status.get("succeeded") == 1

    wait_until(migration_finished, "PgSTAC migration did not finish")
    # Remove the privileged migration input before starting the application.
    api(
        "/api/v1/namespaces/demo/secrets/catalog-postgres-admin",
        bearer,
        method="DELETE",
    )
    api(
        "/apis/apps/v1/namespaces/demo/deployments",
        bearer,
        documents[1],
        method="POST",
        expected=201,
    )
    api(
        "/api/v1/namespaces/demo/services",
        bearer,
        documents[2],
        method="POST",
        expected=201,
    )

    def catalog_ready():
        deployment = api("/apis/apps/v1/namespaces/demo/deployments/catalog", bearer)
        status = deployment.get("status", {})
        return (
            status.get("observedGeneration") == deployment["metadata"]["generation"]
            and status.get("replicas") == 1
            and status.get("readyReplicas") == 1
            and status.get("updatedReplicas") == 1
            and status.get("unavailableReplicas", 0) == 0
        )

    wait_until(catalog_ready, "STAC FastAPI did not become ready")
    api(
        CATALOG_PATH + "/collections",
        bearer,
        {
            "type": "Collection",
            "stac_version": "1.0.0",
            "id": COLLECTION,
            "description": "The Datalab integration catalog.",
            "license": "proprietary",
            "links": [],
            "extent": {
                "spatial": {"bbox": [[16, 47, 18, 49]]},
                "temporal": {"interval": [["2025-01-01T00:00:00Z", None]]},
            },
        },
        method="POST",
        expected=(200, 201),
    )
    api(
        CATALOG_PATH + f"/collections/{COLLECTION}/items",
        bearer,
        {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "catalog-item",
            "collection": COLLECTION,
            "geometry": {"type": "Point", "coordinates": [17, 48]},
            "bbox": [17, 48, 17, 48],
            "properties": {"datetime": "2025-01-01T00:00:00Z"},
            "links": [],
            "assets": {},
        },
        method="POST",
        expected=(200, 201),
    )
    check_catalog(api, bearer)
    before = {
        p["metadata"]["uid"]
        for p in api(
            "/api/v1/namespaces/demo/pods?labelSelector=app%3Dcatalog", bearer
        )["items"]
    }
    api(
        "/apis/apps/v1/namespaces/demo/deployments/catalog",
        bearer,
        {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {"test.datalab/restart": str(time.time())}
                    }
                }
            }
        },
        method="PATCH",
    )
    wait_until(catalog_ready, "STAC FastAPI did not recover after restart")
    after = {
        p["metadata"]["uid"]
        for p in api(
            "/api/v1/namespaces/demo/pods?labelSelector=app%3Dcatalog", bearer
        )["items"]
    }
    assert after - before, "The catalog API did not restart"
    check_catalog(api, bearer)
    print("PASS PostgreSQL catalog survives a STAC API restart", flush=True)


def identity(path, values=None, token=None, method=None):
    data = json.dumps(values).encode() if values is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    context = ssl.create_default_context(cafile="/test/issuer.crt")
    with urlopen(
        Request(
            "https://keycloak.keycloak:8443" + path,
            data=data,
            headers=headers,
            method=method,
        ),
        context=context,
        timeout=30,
    ) as result:
        body = result.read()
        return json.loads(body) if body else None


def token(client, secret, realm="integration", origin="https://keycloak.keycloak:8443"):
    data = urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client,
            "client_secret": secret,
        }
    ).encode()
    context = ssl.create_default_context(cafile="/test/issuer.crt")
    with urlopen(
        Request(f"{origin}/realms/{realm}/protocol/openid-connect/token", data=data),
        context=context,
        timeout=30,
    ) as result:
        return json.load(result)["access_token"]


def admin_token():
    data = urlencode(
        {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "integration-admin",
            "password": "integration-admin",
        }
    ).encode()
    context = ssl.create_default_context(cafile="/test/issuer.crt")
    with urlopen(
        Request(
            "https://keycloak.keycloak:8443/realms/master/protocol/openid-connect/token",
            data=data,
        ),
        context=context,
        timeout=30,
    ) as result:
        return json.load(result)["access_token"]


def negative_token(label, roles, audience=LAB, lifetime=None):
    admin = admin_token()
    client = "xyz-" + label
    clients = identity(
        "/admin/realms/integration/clients?clientId=" + client, token=admin
    )
    for existing in clients:
        identity(
            "/admin/realms/integration/clients/" + existing["id"],
            token=admin,
            method="DELETE",
        )
    claims = json.dumps({LAB: {"roles": roles}})
    identity(
        "/admin/realms/integration/clients",
        {
            "clientId": client,
            "secret": "xyz-test-secret",
            "enabled": True,
            "serviceAccountsEnabled": True,
            "standardFlowEnabled": False,
            "fullScopeAllowed": False,
            "attributes": {"access.token.lifespan": str(lifetime)} if lifetime else {},
            "protocolMappers": [
                {
                    "name": "xyz-roles",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-hardcoded-claim-mapper",
                    "config": {
                        "claim.name": "resource_access",
                        "claim.value": claims,
                        "jsonType.label": "JSON",
                        "access.token.claim": "true",
                        "id.token.claim": "false",
                    },
                },
                {
                    "name": "xyz-audience",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-audience-mapper",
                    "config": {
                        "included.custom.audience": audience,
                        "access.token.claim": "true",
                    },
                },
            ],
        },
        token=admin,
    )
    return token(client, "xyz-test-secret")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gateway_ip")
    parser.add_argument("--other-only", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--api-only", action="store_true")
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--revoked", action="store_true")
    args = parser.parse_args()
    context = ssl.create_default_context(cafile="/test/gateway.crt")

    def api(
        path,
        bearer="",
        body=None,
        method="GET",
        expected=200,
        raw=False,
        instance="vc0",
    ):
        connection = http.client.HTTPSConnection(HOST, timeout=30, context=context)
        connection.sock = context.wrap_socket(
            socket.create_connection((args.gateway_ip, 443), timeout=30),
            server_hostname=HOST,
        )
        headers = {
            "Content-Type": (
                "application/merge-patch+json"
                if method == "PATCH"
                else "application/json"
            )
        }
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        connection.request(
            method,
            f"/.{instance}" + path,
            body=json.dumps(body) if body is not None else None,
            headers=headers,
        )
        result = connection.getresponse()
        data = result.read()
        connection.close()
        allowed = expected if isinstance(expected, tuple) else (expected,)
        assert (
            result.status in allowed
        ), f"{method} {path}: expected {expected}, got {result.status}"
        return data.decode() if raw else (json.loads(data) if data else None)

    def profile_token(profile, instance="vc0"):
        config = json.loads(Path(f"/profiles/{profile}/kubeconfig").read_text())
        assert (
            config["clusters"][0]["cluster"]["server"] == f"https://{HOST}/.{instance}"
        )
        assert (
            base64.b64decode(
                config["clusters"][0]["cluster"]["certificate-authority-data"]
            )
            == Path("/test/gateway.crt").read_bytes()
        )
        assert set(config["users"][0]["user"]) == {"exec"}
        command = config["users"][0]["user"]["exec"]
        credential = subprocess.run(
            [command["command"], *command["args"]],
            check=True,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                **{item["name"]: item["value"] for item in command["env"]},
            },
        )
        return json.loads(credential.stdout)["status"]["token"]

    if args.other_only:
        other = profile_token("other", "vc1")
        assert (
            api(
                "/api/v1/namespaces/default/configmaps/xyz-instance",
                other,
                instance="vc1",
            )["data"]["instance"]
            == "vc1"
        )
        print("PASS vc1 remains available after vc0 removal", flush=True)
        return

    if args.api_only:
        deadline = time.monotonic() + 120
        while True:
            try:
                api("/api/v1/namespaces", profile_token("administrator"))
                break
            except (AssertionError, OSError, subprocess.CalledProcessError):
                if time.monotonic() > deadline:
                    raise
                time.sleep(2)
        print("PASS HTTPS API and generated credentials after re-enable", flush=True)
        return

    bearer = profile_token("administrator")
    marker = Path("/tmp/xyz-editor-token")
    if args.read_only or args.revoked:
        editor = marker.read_text()
        deadline = time.monotonic() + 180
        while True:
            try:
                api(
                    "/api/v1/namespaces/demo/configmaps/xyz-editor",
                    editor,
                    expected=(401, 403) if args.revoked else 200,
                )
                api(
                    "/api/v1/namespaces/demo/configmaps",
                    editor,
                    method="POST",
                    body={
                        "apiVersion": "v1",
                        "kind": "ConfigMap",
                        "metadata": {"name": "xyz-denied"},
                    },
                    expected=(401, 403),
                )
                claims = json.loads(
                    base64.urlsafe_b64decode(editor.split(".")[1] + "==")
                )
                assert (
                    claims["exp"] > time.time()
                ), "Profile token expired before revocation was verified"
                break
            except (AssertionError, OSError):
                if time.monotonic() > deadline:
                    raise
                time.sleep(3)
        api("/api/v1/namespaces/demo/configmaps/xyz-editor", bearer)
        print(
            (
                "PASS revoked profile with retained namespace data"
                if args.revoked
                else "PASS profile downgrade removes write permission"
            ),
            flush=True,
        )
        return
    other = profile_token("other", "vc1")
    api("/api/v1/namespaces", other, instance="vc1")
    api("/api/v1/namespaces", other, expected=(401, 403))
    api("/api/v1/namespaces", bearer, expected=(401, 403), instance="vc1")
    print("PASS each virtual cluster rejects the other profile", flush=True)
    editor = profile_token("editor")
    marker.write_text(editor)
    for value, expected_role in (
        (bearer, "vcluster:vc0:cluster-admin"),
        (editor, "vcluster:vc0:namespace-demo"),
    ):
        claims = json.loads(base64.urlsafe_b64decode(value.split(".")[1] + "=="))
        assert claims["resource_access"][LAB]["roles"] == [expected_role]
        assert LAB in (
            [claims["aud"]] if isinstance(claims["aud"], str) else claims["aud"]
        )
    deadline = time.monotonic() + 90
    while True:
        try:
            api("/api/v1/namespaces", bearer)
            break
        except (AssertionError, OSError):
            if time.monotonic() > deadline:
                raise
            time.sleep(3)
    print("PASS HTTPS prefix route and downloaded credential helper", flush=True)

    def volume_pod(pod_name, command):
        api(
            "/api/v1/namespaces/demo/pods",
            editor,
            method="POST",
            expected=201,
            body={
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {"name": pod_name},
                "spec": {
                    "containers": [
                        {
                            "name": "worker",
                            "image": "busybox:1.36.1",
                            "command": ["sh", "-c", command],
                            "resources": {
                                "requests": {
                                    "cpu": "10m",
                                    "memory": "16Mi",
                                    "ephemeral-storage": "1Mi",
                                },
                                "limits": {
                                    "cpu": "100m",
                                    "memory": "64Mi",
                                    "ephemeral-storage": "32Mi",
                                },
                            },
                            "volumeMounts": [{"name": "data", "mountPath": "/data"}],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "data",
                            "persistentVolumeClaim": {"claimName": "xyz-data"},
                        }
                    ],
                },
            },
        )
        deadline = time.monotonic() + 300
        while (
            api("/api/v1/namespaces/demo/pods/" + pod_name, editor)
            .get("status", {})
            .get("phase")
            != "Running"
        ):
            assert time.monotonic() < deadline, "PVC workload did not start"
            time.sleep(3)

    path = "/api/v1/namespaces/default/configmaps/xyz-marker"
    if args.check_only:
        assert api(path, bearer)["data"]["marker"] == "persistent"
        volume_pod("xyz-volume-reader", "cat /data/marker && echo && sleep 3600")
        deadline = time.monotonic() + 60
        while (
            api(
                "/api/v1/namespaces/demo/pods/xyz-volume-reader/log", editor, raw=True
            ).strip()
            != "persistent"
        ):
            assert time.monotonic() < deadline, "Workload PVC data did not survive"
            time.sleep(2)
        check_catalog(api, bearer)
        print(
            "PASS cluster state and workload PVC data after control-plane restart",
            flush=True,
        )
        return
    for instance, value in (("vc0", bearer), ("vc1", other)):
        api(
            "/api/v1/namespaces/default/configmaps",
            value,
            method="POST",
            expected=201,
            instance=instance,
            body={
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": "xyz-instance"},
                "data": {"instance": instance},
            },
        )
    assert (
        api("/api/v1/namespaces/default/configmaps/xyz-instance", bearer)["data"][
            "instance"
        ]
        == "vc0"
    )
    assert (
        api(
            "/api/v1/namespaces/default/configmaps/xyz-instance", other, instance="vc1"
        )["data"]["instance"]
        == "vc1"
    )
    print("PASS same-named objects have separate state in vc0 and vc1", flush=True)
    classes = api("/apis/storage.k8s.io/v1/storageclasses", bearer)["items"]
    assert {item["metadata"]["name"] for item in classes} == {"standard"}
    assert (
        classes[0]["metadata"]["annotations"][
            "storageclass.kubernetes.io/is-default-class"
        ]
        == "true"
    )
    print(
        "PASS virtual API exposes only the configured default StorageClass", flush=True
    )
    if api(path, bearer, expected=(200, 404)).get("kind") == "ConfigMap":
        api(path, bearer, method="DELETE")
    api(
        "/api/v1/namespaces/default/configmaps",
        bearer,
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "xyz-marker"},
            "data": {"marker": "persistent"},
        },
        method="POST",
        expected=201,
    )
    api(
        "/apis/apiextensions.k8s.io/v1/customresourcedefinitions/checks.xyz.internal",
        bearer,
        method="DELETE",
        expected=(200, 404),
    )
    api(
        "/apis/apiextensions.k8s.io/v1/customresourcedefinitions",
        bearer,
        {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "metadata": {"name": "checks.xyz.internal"},
            "spec": {
                "group": "xyz.internal",
                "scope": "Namespaced",
                "names": {"plural": "checks", "singular": "check", "kind": "Check"},
                "versions": [
                    {
                        "name": "v1",
                        "served": True,
                        "storage": True,
                        "schema": {"openAPIV3Schema": {"type": "object"}},
                    }
                ],
            },
        },
        method="POST",
        expected=201,
    )
    api(
        "/api/v1/namespaces/default/pods/xyz-workload",
        bearer,
        method="DELETE",
        expected=(200, 404),
    )
    api(
        "/api/v1/namespaces/default/pods",
        bearer,
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "xyz-workload"},
            "spec": {
                "containers": [
                    {
                        "name": "worker",
                        "image": "busybox:1.36.1",
                        "command": ["sleep", "3600"],
                        "resources": {
                            "requests": {
                                "cpu": "10m",
                                "memory": "16Mi",
                                "ephemeral-storage": "1Mi",
                            },
                            "limits": {
                                "cpu": "100m",
                                "memory": "64Mi",
                                "ephemeral-storage": "32Mi",
                            },
                        },
                    }
                ]
            },
        },
        method="POST",
        expected=201,
    )
    deadline = time.monotonic() + 300
    while (
        api("/api/v1/namespaces/default/pods/xyz-workload", bearer)
        .get("status", {})
        .get("phase")
        != "Running"
    ):
        assert time.monotonic() < deadline, "Virtual workload did not start"
        time.sleep(3)
    print(
        "PASS administrator profile can write data, install a CRD, and run a workload",
        flush=True,
    )
    api(
        "/api/v1/namespaces/demo/configmaps",
        editor,
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "xyz-editor"},
            "data": {"marker": "retained"},
        },
        method="POST",
        expected=201,
    )
    api("/api/v1/namespaces/default/configmaps", editor, expected=403)
    api(
        "/api/v1/namespaces",
        editor,
        method="POST",
        body={
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": "xyz-denied"},
        },
        expected=403,
    )
    api("/apis/apiextensions.k8s.io/v1/customresourcedefinitions", editor, expected=403)
    api(
        "/apis/rbac.authorization.k8s.io/v1/clusterrolebindings",
        editor,
        method="POST",
        body={
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRoleBinding",
            "metadata": {"name": "xyz-denied"},
            "roleRef": {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "ClusterRole",
                "name": "cluster-admin",
            },
            "subjects": [
                {
                    "kind": "Group",
                    "apiGroup": "rbac.authorization.k8s.io",
                    "name": f"datalab:{LAB}:vcluster:vc0:namespace-demo",
                }
            ],
        },
        expected=403,
    )
    api(
        "/api/v1/namespaces/demo/persistentvolumeclaims",
        editor,
        method="POST",
        expected=201,
        body={
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": "xyz-data"},
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": "standard",
                "resources": {"requests": {"storage": "1Mi"}},
            },
        },
    )
    volume_pod(
        "xyz-volume-writer",
        "printf persistent > /data/marker; echo xyz-log; mkdir -p /www; echo xyz-forward > /www/index.html; httpd -p 8080 -h /www; sleep 3600",
    )
    assert (
        api("/api/v1/namespaces/demo/persistentvolumeclaims/xyz-data", editor)[
            "status"
        ]["phase"]
        == "Bound"
    )
    print(
        "PASS namespace profile, denied escalation, and host-provisioned workload PVC",
        flush=True,
    )

    class GatewayProxy(http.server.BaseHTTPRequestHandler):
        # Keep the public hostname and TLS checks without changing cluster DNS.
        def do_CONNECT(self):
            assert self.path == HOST + ":443"
            with socket.create_connection(
                (args.gateway_ip, 443), timeout=30
            ) as upstream:
                self.send_response(200)
                self.end_headers()
                try:
                    while True:
                        readable, _, _ = select.select(
                            [self.connection, upstream], [], [], 30
                        )
                        if not readable:
                            return
                        for source in readable:
                            chunk = source.recv(65536)
                            if not chunk:
                                return
                            (
                                upstream
                                if source is self.connection
                                else self.connection
                            ).sendall(chunk)
                except ConnectionError:
                    return

        def log_message(self, *_):
            pass

    proxy = http.server.ThreadingHTTPServer(("127.0.0.1", 0), GatewayProxy)
    proxy.daemon_threads = True
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    config = json.loads(Path("/profiles/editor/kubeconfig").read_text())
    config["clusters"][0]["cluster"][
        "proxy-url"
    ] = f"http://127.0.0.1:{proxy.server_port}"
    kubeconfig = Path("/tmp/xyz-kubeconfig")
    kubeconfig.write_text(json.dumps(config))
    kubeconfig.chmod(0o600)
    command = [
        "/tmp/kubectl",
        "--kubeconfig",
        str(kubeconfig),
        "--context",
        config["current-context"],
        "-n",
        "demo",
    ]
    try:
        result = subprocess.run(
            [*command, "exec", "xyz-volume-writer", "--", "printf", "xyz-exec"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0 and result.stdout == "xyz-exec", result.stderr
        result = subprocess.run(
            [*command, "logs", "xyz-volume-writer"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0 and "xyz-log" in result.stdout, result.stderr
        events = api(
            "/api/v1/namespaces/demo/configmaps?watch=true&timeoutSeconds=2",
            editor,
            raw=True,
        )
        assert any(
            json.loads(line)["object"]["metadata"]["name"] == "xyz-editor"
            for line in events.splitlines()
            if line.strip()
        ), events
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        forward = subprocess.Popen(
            [*command, "port-forward", "pod/xyz-volume-writer", f"{port}:8080"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 45
            while True:
                try:
                    with urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
                        assert response.read().strip() == b"xyz-forward"
                    break
                except OSError:
                    if forward.poll() is not None or time.monotonic() > deadline:
                        raise AssertionError(
                            "Port forwarding failed: "
                            + (
                                forward.stderr.read()
                                if forward.poll() is not None
                                else "timeout"
                            )
                        )
                    time.sleep(1)
        finally:
            forward.terminate()
            forward.communicate(timeout=10)
        print(
            "PASS kubectl exec, logs, watch, and port forwarding through /.vc0",
            flush=True,
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        kubeconfig.unlink()
    deploy_catalog(api, editor)
    api("/api/v1/namespaces", expected=(401, 403))
    for label, roles, audience in (
        ("access", ["ws_access"], LAB),
        ("admin", ["ws_admin"], LAB),
        ("api", ["ws_api"], LAB),
        ("no-role", [], LAB),
        ("unknown-profile", ["vcluster-unconfigured"], LAB),
        ("wrong-audience", ["vcluster:vc0:cluster-admin"], "another-datalab"),
    ):
        denied = negative_token(label, roles, audience)
        claims = json.loads(base64.urlsafe_b64decode(denied.split(".")[1] + "=="))
        assert claims["resource_access"][LAB]["roles"] == roles
        assert audience in (
            [claims["aud"]] if isinstance(claims["aud"], str) else claims["aud"]
        )
        api("/api/v1/namespaces", denied, expected=(401, 403))
        print("PASS denied " + label, flush=True)
    wrong_issuer = token(
        Path("/profiles/administrator/client-id").read_text().strip(),
        Path("/profiles/administrator/client-secret").read_text().strip(),
        origin="http://keycloak.keycloak:8080",
    )
    claims = json.loads(base64.urlsafe_b64decode(wrong_issuer.split(".")[1] + "=="))
    assert claims["iss"] != ISSUER
    api("/api/v1/namespaces", wrong_issuer, expected=(401, 403))
    print("PASS denied wrong issuer", flush=True)
    expired = negative_token("expired", ["vcluster:vc0:cluster-admin"], lifetime=1)
    time.sleep(3)
    api("/api/v1/namespaces", expired, expected=(401, 403))
    parts = bearer.split(".")
    # A changed signature must fail even when claims still contain an allowed role.
    signature = bytearray(base64.urlsafe_b64decode(parts[2] + "=="))
    signature[0] ^= 1
    parts[2] = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    api("/api/v1/namespaces", ".".join(parts), expected=(401, 403))
    print("PASS denied expired token and invalid signature", flush=True)


if __name__ == "__main__":
    main()
