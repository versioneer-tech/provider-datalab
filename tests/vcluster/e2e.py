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


def verify_member_roles(removed, instances):
    expected = set() if removed else {
        f"vcluster_{instance}_cluster-admin" for instance in instances
    }

    def assigned():
        admin = admin_token()
        clients = identity("/admin/realms/integration/clients?clientId=" + LAB, token=admin)
        users = identity("/admin/realms/integration/users?username=verify-s3&exact=true", token=admin)
        assert len(clients) == len(users) == 1
        client = "/admin/realms/integration/clients/" + clients[0]["id"]
        claims = identity(
            client + "/evaluate-scopes/generate-example-access-token?"
            + urlencode({"userId": users[0]["id"], "scope": "openid"}),
            token=admin,
        )
        roles = set(claims.get("resource_access", {}).get(LAB, {}).get("roles", []))
        if {role for role in roles if role.startswith("vcluster_")} != expected:
            return False
        assert ("ws_access" in roles) == (not removed)
        account = identity(client + "/service-account-user", token=admin)
        mappings = identity(
            "/admin/realms/integration/users/" + account["id"]
            + "/role-mappings/clients/" + clients[0]["id"] + "/composite",
            token=admin,
        )
        assert {role["name"] for role in mappings} == {"ws_api"}
        return True

    wait_until(assigned, "Datalab member roles did not reach the expected state")
    print("PASS Datalab member token roles and separate ws_api automation permission", flush=True)


def workspace_account():
    admin = admin_token()
    clients = identity("/admin/realms/integration/clients", token=admin)
    owned = [client for client in clients if client["clientId"] == LAB or client["clientId"].startswith(LAB + "-vcluster-")]
    assert len(owned) == 1 and owned[0]["clientId"] == LAB
    client = "/admin/realms/integration/clients/" + owned[0]["id"]
    account = identity(client + "/service-account-user", token=admin)
    mapping = "/admin/realms/integration/users/" + account["id"] + "/role-mappings/clients/" + owned[0]["id"]
    return admin, client, mapping


def set_workspace_roles(roles):
    admin, client, mapping = workspace_account()
    assigned = identity(mapping, token=admin)
    old = [role for role in assigned if role["name"].startswith("vcluster_")]
    if old:
        identity(mapping, old, token=admin, method="DELETE")
    if roles:
        available = identity(client + "/roles", token=admin)
        selected = [role for role in available if role["name"] in roles]
        assert {role["name"] for role in selected} == set(roles)
        identity(mapping, selected, token=admin, method="POST")


def negative_token(label, roles, audience=LAB, lifetime=None):
    admin = admin_token()
    client = "vcluster-test-" + label
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
            "secret": "vcluster-test-secret",
            "enabled": True,
            "serviceAccountsEnabled": True,
            "standardFlowEnabled": False,
            "fullScopeAllowed": False,
            "attributes": {"access.token.lifespan": str(lifetime)} if lifetime else {},
            "protocolMappers": [
                {
                    "name": "test-roles",
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
                    "name": "test-audience",
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
    return token(client, "vcluster-test-secret")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gateway_ip")
    parser.add_argument("--other-only", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--api-only", action="store_true")
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--revoked", action="store_true")
    parser.add_argument("--member-roles", action="store_true")
    parser.add_argument("--member-removed", action="store_true")
    parser.add_argument("--member-instance", action="append")
    args = parser.parse_args()
    if args.member_roles or args.member_removed:
        verify_member_roles(args.member_removed, args.member_instance or ["vc0", "vc1"])
        return
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
        values = {path.name: path.read_text().strip() for path in Path(f"/profiles/{profile}").iterdir() if path.is_file() and not path.name.startswith(".")}
        assert set(values) == {"kubeconfig", "client-id", "issuer-url"}
        assert values["client-id"] == LAB
        assert set(config["users"][0]["user"]) == {"exec"}
        command = config["users"][0]["user"]["exec"]
        assert "env" not in command
        secret_file = next(Path("/oauth") / key for key in ("clientSecret", "client_secret", "attribute.client_secret") if (Path("/oauth") / key).is_file())
        credential = subprocess.run(
            [command["command"], *command["args"]],
            check=True,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "DATALAB_CLIENT_SECRET_FILE": str(secret_file),
            },
        )
        return json.loads(credential.stdout)["status"]["token"]

    def granted_token(profile, role, instance="vc0"):
        # Only this test assigns a vcluster role to the workspace account.
        set_workspace_roles([role])
        try:
            value = profile_token(profile, instance)
            claims = json.loads(base64.urlsafe_b64decode(value.split(".")[1] + "=="))
            assert set(claims["resource_access"][LAB]["roles"]) == {"ws_api", role}
            return value
        finally:
            set_workspace_roles([])

    admin, _, mapping = workspace_account()
    assigned = identity(mapping + "/composite", token=admin)
    assert {role["name"] for role in assigned} == {"ws_api"}
    print("PASS one workspace OAuth client and no automatic vcluster account grant", flush=True)

    if args.other_only:
        other = granted_token("other", "vcluster_vc1_cluster-admin", "vc1")
        assert (
            api(
                "/api/v1/namespaces/default/configmaps/instance-probe",
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
                api("/api/v1/namespaces", granted_token("administrator", "vcluster_vc0_cluster-admin"))
                break
            except (AssertionError, OSError, subprocess.CalledProcessError):
                if time.monotonic() > deadline:
                    raise
                time.sleep(2)
        print("PASS HTTPS API and generated credentials after re-enable", flush=True)
        return

    for profile, instance in (("administrator", "vc0"), ("editor", "vc0"), ("other", "vc1")):
        if args.revoked and profile == "editor":
            continue
        denied = profile_token(profile, instance)
        claims = json.loads(base64.urlsafe_b64decode(denied.split(".")[1] + "=="))
        assert set(claims["resource_access"][LAB]["roles"]) == {"ws_api"}
        api("/api/v1/namespaces", denied, expected=401, instance=instance)
    print("PASS every downloaded profile rejects the workspace account with only ws_api", flush=True)
    bearer = granted_token("administrator", "vcluster_vc0_cluster-admin")
    marker = Path("/tmp/vcluster-editor-token")
    if args.read_only or args.revoked:
        editor = marker.read_text()
        deadline = time.monotonic() + 180
        while True:
            try:
                api(
                    "/api/v1/namespaces/demo/configmaps/editor-probe",
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
                        "metadata": {"name": "denied-probe"},
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
        api("/api/v1/namespaces/demo/configmaps/editor-probe", bearer)
        print(
            (
                "PASS revoked profile with retained namespace data"
                if args.revoked
                else "PASS profile downgrade removes write permission"
            ),
            flush=True,
        )
        return
    other = granted_token("other", "vcluster_vc1_cluster-admin", "vc1")
    api("/api/v1/namespaces", other, instance="vc1")
    api("/api/v1/namespaces", other, expected=(401, 403))
    api("/api/v1/namespaces", bearer, expected=(401, 403), instance="vc1")
    print("PASS each virtual cluster rejects the other profile", flush=True)
    editor = granted_token("editor", "vcluster_vc0_namespace-demo")
    admin_profile = granted_token("administrator", "vcluster_vc0_namespace-demo")
    api("/api/v1/namespaces", admin_profile, expected=403)
    api("/api/v1/namespaces/demo/configmaps", admin_profile)
    print("PASS cluster-admin download keeps the caller's namespace role", flush=True)
    marker.write_text(editor)
    for value, expected_role in (
        (bearer, "vcluster_vc0_cluster-admin"),
        (editor, "vcluster_vc0_namespace-demo"),
    ):
        claims = json.loads(base64.urlsafe_b64decode(value.split(".")[1] + "=="))
        assert set(claims["resource_access"][LAB]["roles"]) == {"ws_api", expected_role}
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
                            "persistentVolumeClaim": {"claimName": "workload-data"},
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

    path = "/api/v1/namespaces/default/configmaps/restart-marker"
    if args.check_only:
        assert api(path, bearer)["data"]["marker"] == "persistent"
        volume_pod("volume-reader", "cat /data/marker && echo && sleep 3600")
        deadline = time.monotonic() + 60
        while (
            api(
                "/api/v1/namespaces/demo/pods/volume-reader/log", editor, raw=True
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
                "metadata": {"name": "instance-probe"},
                "data": {"instance": instance},
            },
        )
    assert (
        api("/api/v1/namespaces/default/configmaps/instance-probe", bearer)["data"][
            "instance"
        ]
        == "vc0"
    )
    assert (
        api(
            "/api/v1/namespaces/default/configmaps/instance-probe", other, instance="vc1"
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
            "metadata": {"name": "restart-marker"},
            "data": {"marker": "persistent"},
        },
        method="POST",
        expected=201,
    )
    api(
        "/apis/apiextensions.k8s.io/v1/customresourcedefinitions/checks.vcluster-test.internal",
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
            "metadata": {"name": "checks.vcluster-test.internal"},
            "spec": {
                "group": "vcluster-test.internal",
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
        "/api/v1/namespaces/default/pods/admin-workload",
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
            "metadata": {"name": "admin-workload"},
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
        api("/api/v1/namespaces/default/pods/admin-workload", bearer)
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
            "metadata": {"name": "editor-probe"},
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
            "metadata": {"name": "denied-probe"},
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
            "metadata": {"name": "denied-probe"},
            "roleRef": {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "ClusterRole",
                "name": "cluster-admin",
            },
            "subjects": [
                {
                    "kind": "Group",
                    "apiGroup": "rbac.authorization.k8s.io",
                    "name": f"datalab:{LAB}:vcluster_vc0_namespace-demo",
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
            "metadata": {"name": "workload-data"},
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": "standard",
                "resources": {"requests": {"storage": "1Mi"}},
            },
        },
    )
    volume_pod(
        "volume-writer",
        "printf persistent > /data/marker; echo stream-log; mkdir -p /www; echo stream-forward > /www/index.html; httpd -p 8080 -h /www; sleep 3600",
    )
    assert (
        api("/api/v1/namespaces/demo/persistentvolumeclaims/workload-data", editor)[
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
    config["users"][0]["user"]["exec"]["env"] = [
        {"name": "DATALAB_ACCESS_TOKEN_FILE", "value": str(marker)},
        {"name": "DATALAB_CLIENT_SECRET_FILE", "value": ""},
    ]
    config["clusters"][0]["cluster"][
        "proxy-url"
    ] = f"http://127.0.0.1:{proxy.server_port}"
    kubeconfig = Path("/tmp/vcluster-kubeconfig")
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
            [*command, "exec", "volume-writer", "--", "printf", "stream-exec"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0 and result.stdout == "stream-exec", result.stderr
        result = subprocess.run(
            [*command, "logs", "volume-writer"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0 and "stream-log" in result.stdout, result.stderr
        events = api(
            "/api/v1/namespaces/demo/configmaps?watch=true&timeoutSeconds=2",
            editor,
            raw=True,
        )
        assert any(
            json.loads(line)["object"]["metadata"]["name"] == "editor-probe"
            for line in events.splitlines()
            if line.strip()
        ), events
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        forward = subprocess.Popen(
            [*command, "port-forward", "pod/volume-writer", f"{port}:8080"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 45
            while True:
                try:
                    with urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
                        assert response.read().strip() == b"stream-forward"
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
        ("wrong-audience", ["vcluster_vc0_cluster-admin"], "another-datalab"),
    ):
        denied = negative_token(label, roles, audience)
        claims = json.loads(base64.urlsafe_b64decode(denied.split(".")[1] + "=="))
        assert claims["resource_access"][LAB]["roles"] == roles
        assert audience in (
            [claims["aud"]] if isinstance(claims["aud"], str) else claims["aud"]
        )
        api("/api/v1/namespaces", denied, expected=(401, 403))
        print("PASS denied " + label, flush=True)
    set_workspace_roles(["vcluster_vc0_cluster-admin"])
    try:
        wrong_issuer = token(
            Path("/profiles/administrator/client-id").read_text().strip(),
            next((Path("/oauth") / key).read_text().strip() for key in ("clientSecret", "client_secret", "attribute.client_secret") if (Path("/oauth") / key).is_file()),
            origin="http://keycloak.keycloak:8080",
        )
    finally:
        set_workspace_roles([])
    claims = json.loads(base64.urlsafe_b64decode(wrong_issuer.split(".")[1] + "=="))
    assert claims["iss"] != ISSUER
    assert "vcluster_vc0_cluster-admin" in claims["resource_access"][LAB]["roles"]
    api("/api/v1/namespaces", wrong_issuer, expected=(401, 403))
    print("PASS denied wrong issuer", flush=True)
    expired = negative_token("expired", ["vcluster_vc0_cluster-admin"], lifetime=1)
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
