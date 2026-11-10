# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check OAuth2 discovery without credential disclosure."""

import base64
from copy import deepcopy
import json

from render import arguments, environment, render


def main():
    args = arguments()
    env = environment()
    env["data"]["defaults"] = {"data": {"enabled": False}, "registry": {"enabled": False}}
    env["data"]["iam"]["redirectURIs"] = ["http://localhost:8080/callback"] * 2
    env["data"]["iam"]["webOrigins"] = ["https://tools.example"]
    source = {
        "apiVersion": "versioneer.at/v1", "kind": "Datalab",
        "metadata": {"name": "s-joe", "namespace": "workspace"},
        "spec": {"users": []},
        "status": {"connections": [{"name": "retired-client", "type": "oauth2", "ready": True,
                                    "secretRef": {"name": "retired", "namespace": "workspace"}}],
                   "oauth2": [{"name": "retired-client", "type": "client",
            "issuerUrl": "https://identity.example/realms/retired", "ready": True,
            "secretRef": {"name": "retired", "namespace": "workspace"},
        }]},
    }
    client_id = "s-john"
    expected = [{"name": client_id, "type": "client",
        "issuerUrl": env["data"]["iam"]["issuerURL"],
        "secretRef": {"name": "s-joe-oauth-client", "namespace": "workspace"},
        "ready": True,
    }]
    conditions = [{"type": "Ready", "status": "True"}, {"type": "Synced", "status": "True"}]
    client = {
        "apiVersion": "openidclient.keycloak.m.crossplane.io/v1alpha1", "kind": "Client",
        "metadata": {"name": "s-joe", "namespace": "workspace", "annotations": {
            "crossplane.io/composition-resource-name": "keycloak-client-s-joe",
        }},
        "spec": {"forProvider": {"clientId": client_id}},
        "status": {"conditions": conditions, "atProvider": {"id": "internal-uuid", "clientId": client_id}},
    }
    observer = {
        "apiVersion": "kubernetes.m.crossplane.io/v1alpha1", "kind": "Object",
        "metadata": {"name": "observe-oauth-client-secret-s-joe", "namespace": "workspace", "annotations": {
            "crossplane.io/composition-resource-name": "observe-oauth-client-secret-s-joe",
        }},
        "status": {"conditions": deepcopy(conditions), "atProvider": {"manifest": {
            "apiVersion": "v1", "kind": "Secret",
            "metadata": {"name": "s-joe-oauth-client", "namespace": "workspace"},
            "data": {"clientID": base64.b64encode(client_id.encode()).decode(),
                     "clientSecret": base64.b64encode(b"oauth2-sensitive-value").decode()},
        }}},
    }

    def discovery(resources):
        result = resources["composite"]["status"]
        assert all(c["type"] != "oauth2" for c in result["connections"])
        assert "oauth2-sensitive-value" not in json.dumps(result)
        assert base64.b64encode(b"oauth2-sensitive-value").decode() not in json.dumps(result)
        return result["oauth2"]

    def status(observed):
        return discovery(render(args, env, source, observed, include_composite=True))

    initial = render(args, env, source, [client, observer], include_composite=True)
    client_config = initial["keycloak-client-s-joe"]["spec"]["forProvider"]
    assert client_config["validRedirectUris"] == [
        "https://s-joe.lab.acme.com/oauth2/callback", "http://localhost:8080/callback",
    ]
    assert client_config["webOrigins"] == ["https://s-joe.lab.acme.com", "https://tools.example"]
    assert "oauth2-client-secret-s-joe" not in initial
    assert discovery(initial) == expected
    print("PASS OAuth2 discovery uses the actual client ID, contains only metadata, and stays outside connections")

    for index in (0, 1):
        pending = deepcopy([client, observer])
        pending[index]["status"]["conditions"][0]["status"] = "False"
        result = status(pending)
        assert result == [{**expected[0], "ready": False}]
    pending = deepcopy(client)
    pending["status"]["conditions"] = [
        {"type": "Ready", "status": "True"}, {"type": "Synced", "status": "False"}
    ]
    assert status([pending, observer])[0]["ready"] is False
    for values in ({}, {"clientSecret": base64.b64encode(b"value").decode(), "clientID": base64.b64encode(b"another-client").decode()}):
        pending = deepcopy(observer)
        pending["status"]["atProvider"]["manifest"]["data"] = values
        assert status([client, pending])[0]["ready"] is False
    print("PASS OAuth2 readiness requires a ready client and matching observed credentials")

    for observed in ([client], [observer]):
        assert status(observed) == []
    deleting = deepcopy(client)
    deleting["metadata"]["deletionTimestamp"] = "2026-11-04T12:00:00Z"
    assert status([deleting, observer]) == []
    cached = deepcopy(observer)
    cached["status"]["conditions"] = [
        {"type": "Ready", "status": "True"},
        {"type": "Synced", "status": "False", "reason": "ReconcileError",
         "message": "observe failed: external resource does not exist"},
    ]
    assert status([client, cached]) == []
    wrong_namespace = deepcopy(observer)
    wrong_namespace["status"]["atProvider"]["manifest"]["metadata"]["namespace"] = "another-workspace"
    assert status([client, wrong_namespace]) == []
    print("PASS missing, removed, or mismatched sources clear stale OAuth2 discovery entries")

if __name__ == "__main__":
    main()
