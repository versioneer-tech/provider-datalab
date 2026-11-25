# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check service credential publication in the Datalab namespace."""

import base64
from copy import deepcopy
import json

from render import arguments, environment, render


def encoded(values):
    return {key: base64.b64encode(value.encode()).decode() for key, value in values.items()}


def main():
    args = arguments()
    env = environment()
    env["data"].update({"packageR": {"enabled": False}, "registry": {"enabled": False}})
    env["data"]["customSecrets"] = [{"name": "apikey"}]
    source = {
        "apiVersion": "versioneer.at/v1", "kind": "Datalab",
        "metadata": {"name": "s-joe", "namespace": "teams", "uid": "test-datalab"},
        "spec": {"stores": {"prod": {"type": "postgres", "names": ["app"]},
                            "cache": {"type": "redis", "names": ["sessions", "jobs"]}}},
    }
    instances = {"postgres": "prod", "redis": "cache"}
    values = {
        "prod-superuser": {"host": "prod-rw.s-joe.svc", "port": "5432",
                                  "username": "postgres", "password": "test-postgres-password",
                                  "dbname": "app", "uri": "postgresql://postgres:test-postgres-password@prod-rw.s-joe.svc:5432/app",
                                  "jdbc-uri": "jdbc:postgresql://prod/app", "verifier": "test-internal"},
        "cache-redis-auth": {"user": "default", "password": "test-redis-password", "internal": "test-internal"},
        "apikey": {"token": "test-custom-token", "endpoint": "https://example.invalid"},
    }

    def run(xr, config, observed):
        return render(args, config, xr, observed, include_composite=True)

    def connections(resources):
        return resources["composite"]["status"]["connections"]

    def copies(resources):
        references = {
            (connection["secretRef"]["namespace"], connection["secretRef"]["name"])
            for connection in connections(resources)
        }
        # Normalized service outputs are separate from the copies used for discovery.
        return {key: body for key, body in resources.items() if body.get("kind") == "Secret"
                and body["metadata"].get("labels", {}).get("datalabs.versioneer.at/connection")
                and (body["metadata"]["namespace"], body["metadata"]["name"]) in references}

    def scenario(xr):
        name = xr["metadata"]["name"]
        initial = run(xr, env, [])
        assert len(connections(initial)) == 2 and not any(c["ready"] for c in connections(initial))
        assert not copies(initial)
        observed = []
        for key, body in initial.items():
            spec = body.get("spec", {})
            manifest = spec.get("forProvider", {}).get("manifest", {})
            if spec.get("managementPolicies") != ["Observe"] or manifest.get("metadata", {}).get("name") not in values:
                continue
            assert manifest["metadata"]["namespace"] == name
            body = deepcopy(body)
            manifest = deepcopy(manifest)
            manifest["metadata"]["ownerReferences"] = [{"apiVersion": "v1", "kind": "Pod", "name": "source", "uid": "source-owner"}]
            manifest["data"] = encoded(values[manifest["metadata"]["name"]])
            body["status"] = {"atProvider": {"manifest": manifest}, "conditions": [
                {"type": "Ready", "status": "True"}, {"type": "Synced", "status": "True"}]}
            observed.append(body)
        return observed

    observed = scenario(source)
    pending = run(source, env, observed)
    published = copies(pending)
    assert len(published) == 3 and not any(c["ready"] for c in connections(pending))
    expected = {
        "postgres": encoded({("user" if key == "username" else key): value for key, value in values["prod-superuser"].items() if key not in ("verifier", "jdbc-uri")}),
        "redis": encoded({"user": "default", "password": "test-redis-password"}),
        "custom": encoded(values["apikey"]),
    }
    for kind, instance in instances.items():
        names = source["spec"]["stores"][instance]["names"]
        expected[kind].update(encoded({"names": json.dumps(names)}))
        if kind == "redis":
            expected[kind].update(encoded({"prefixes": json.dumps({name: name + ":" for name in names})}))
    for connection in connections(pending):
        ref = connection["secretRef"]
        if connection["type"] in instances:
            assert connection["names"] == source["spec"]["stores"][connection["name"]]["names"]
        secret = next(body for body in published.values() if body["metadata"]["name"] == ref["name"])
        assert ref["namespace"] == secret["metadata"]["namespace"] == source["metadata"]["namespace"]
        assert secret["data"] == expected[connection["type"]]
        assert secret["metadata"]["ownerReferences"] == [{
            "apiVersion": source["apiVersion"], "kind": "Datalab", "name": "s-joe",
            "uid": "test-datalab", "controller": True, "blockOwnerDeletion": True,
        }]
        assert "s-joe" in ref["name"] and connection["type"] in ref["name"] and connection["name"] in ref["name"]
    ready = run(source, env, [*observed, *published.values()])
    assert all(c["ready"] for c in connections(ready))
    assert not any(value in json.dumps(ready["composite"]["status"]) for value in expected["custom"].values())
    print("PASS service copies preserve connection fields, exclude operator internals, and have local ownership")
    print("PASS connections wait for publication in the Datalab namespace, independent of storage credentials")

    for secret_type, fields, expected_type in (
        ("kubernetes.io/dockerconfigjson", {".dockerconfigjson": '{"auths":{}}'}, "kubernetes.io/dockerconfigjson"),
        ("kubernetes.io/service-account-token", {"token": "test-account-token"}, "Opaque"),
    ):
        typed_sources = deepcopy(observed)
        custom_source = next(body for body in typed_sources
                             if body["status"]["atProvider"]["manifest"]["metadata"]["name"] == "apikey")
        custom_source["status"]["atProvider"]["manifest"].update(type=secret_type, data=encoded(fields))
        typed = run(source, env, typed_sources)
        ref = next(c["secretRef"] for c in connections(typed) if c["type"] == "custom")
        copy = next(body for body in copies(typed).values() if body["metadata"]["name"] == ref["name"])
        assert copy["type"] == expected_type and copy["data"] == encoded(fields)
    print("PASS custom connection copies preserve usable Secret types without binding copied account tokens")

    sanitized = deepcopy(observed)
    required_secrets = []
    for body in sanitized:
        manifest = body.get("status", {}).get("atProvider", {}).get("manifest", {})
        if manifest.get("kind") != "Secret":
            continue
        required_secrets.append(deepcopy(manifest))
        manifest["data"] = {"redacted": None}
        body["status"]["atProvider"]["raw"] = {"manifest": deepcopy(required_secrets[-1])}
    secured = run(source, [env, *required_secrets], [*sanitized, *published.values()])
    assert copies(secured) == published
    assert all(c["ready"] for c in connections(secured))
    for kind in ("postgres", "redis"):
        key = f"connection-s-joe-{kind}-{instances[kind]}"
        assert secured[key]["stringData"] == ready[key]["stringData"]
    rotated = deepcopy(observed)
    for body in rotated:
        data = body["status"]["atProvider"]["manifest"]["data"]
        key = "token" if "token" in data else "password"
        data[key] = encoded({key: "test-rotated"})[key]
        if "uri" in data:
            data["uri"] = encoded({"uri": "postgresql://postgres:test-rotated@prod/app"})["uri"]
    rotated_secrets = [body["status"]["atProvider"]["manifest"] for body in rotated]
    rotating = run(source, [env, *rotated_secrets], [*sanitized, *published.values()])
    current = copies(rotating)
    assert set(current) == set(published)
    assert all(current[key]["data"] != published[key]["data"] for key in current)
    assert not any(c["ready"] for c in connections(rotating))
    for kind in ("postgres", "redis"):
        service_values = rotating[f"connection-s-joe-{kind}-{instances[kind]}"]["stringData"]
        assert service_values["password"] == "test-rotated"
    updated = run(source, [env, *rotated_secrets], [*sanitized, *current.values()])
    assert all(c["ready"] for c in connections(updated))
    missing_secured = run(source, env, [*sanitized, *published.values()])
    assert not copies(missing_secured)
    assert not any(c["ready"] for c in connections(missing_secured))
    assert all(f"connection-s-joe-{kind}-{instances[kind]}" not in missing_secured for kind in ("postgres", "redis"))
    print("PASS source Secret rotation updates copies and readiness despite stale, redacted observer data")

    unavailable = deepcopy(rotated)
    for body in unavailable:
        body["status"]["conditions"][1].update(status="False", message="observe failed: external resource does not exist")
    stale = deepcopy(source)
    stale["status"] = deepcopy(ready["composite"]["status"])
    lost = run(stale, env, [*unavailable, *current.values()])
    assert not copies(lost)
    assert len(connections(lost)) == 2 and not any(c["ready"] for c in connections(lost))
    restored = run(lost["composite"], env, [*rotated, *current.values()])
    assert all(c["ready"] for c in connections(restored))
    print("PASS unavailable sources remove stale copies and readiness; recovery republishes current credentials")

    for kind, secret_name, field in (
        ("postgres", "prod-superuser", "password"),
        ("redis", "cache-redis-auth", "user"),
    ):
        incomplete = deepcopy(observed)
        credential = next(body for body in incomplete
                          if body["status"]["atProvider"]["manifest"]["metadata"]["name"] == secret_name)
        credential["status"]["atProvider"]["manifest"]["data"].pop(field)
        missing = run(source, env, [*incomplete, *published.values()])
        assert not next(c["ready"] for c in connections(missing) if c["type"] == kind), kind
        assert len(copies(missing)) == 2, kind
    print("PASS incomplete service credentials prevent publication and readiness")

    other = deepcopy(source)
    other["metadata"].update(name="s-john", uid="test-other-datalab")
    other_sources = scenario(other)
    for body in other_sources:
        data = body["status"]["atProvider"]["manifest"]["data"]
        field = "token" if "token" in data else "password"
        data[field] = encoded({field: "test-john-credential"})[field]
    separate = run(other, env, other_sources)
    assert {c["secretRef"]["name"] for c in connections(pending)}.isdisjoint(
        c["secretRef"]["name"] for c in connections(separate))
    assert len({c["secretRef"]["name"] for c in connections(pending)}) == 3
    assert all(encoded({"value": "test-john-credential"})["value"] in body["data"].values()
               for body in copies(separate).values())
    print("PASS connection names are unique across services and Datalabs")

    removed = deepcopy(stale)
    removed["spec"]["stores"] = {}
    retired_env = deepcopy(env)
    retired_env["data"]["customSecrets"] = []
    retired = run(removed, retired_env, [*observed, *published.values()])
    assert not copies(retired) and not connections(retired)
    print("PASS removing services clears their connections")


if __name__ == "__main__":
    main()
