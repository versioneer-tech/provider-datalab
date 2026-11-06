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
    env["data"]["defaults"] = {"data": {"enabled": False}, "registry": {"enabled": False}}
    env["data"]["customSecrets"] = [{"name": "apikey"}]
    source = {
        "apiVersion": "pkg.internal/v1beta2", "kind": "Datalab",
        "metadata": {"name": "s-joe", "namespace": "teams", "uid": "test-datalab"},
        "spec": {"sessions": [], "databases": {"prod": {"names": ["app"]}},
                 "documentStores": {"prod": {"type": "mongo"}},
                 "cacheStores": {"prod": {"type": "redis"}}},
    }
    values = {
        "prod-pguser-postgres": {"host": "prod-primary.s-joe-runtime.svc", "port": "5432",
                                  "user": "postgres", "password": "test-postgres-password",
                                  "dbname": "app", "uri": "postgresql://postgres:test-postgres-password@prod/app",
                                  "jdbc-uri": "jdbc:postgresql://prod/app", "verifier": "test-internal"},
        "prod-mongodb-auth": {"user": "prod-app", "password": "test-mongo-password", "internal": "test-internal"},
        "prod-redis-auth": {"user": "default", "password": "test-redis-password", "internal": "test-internal"},
        "apikey": {"token": "test-custom-token", "endpoint": "https://example.invalid"},
    }

    def run(xr, config, observed):
        return render(args, config, xr, observed, include_composite=True)

    def connections(resources):
        return resources["composite"]["status"]["connections"]

    def copies(resources):
        return {key: body for key, body in resources.items() if body.get("kind") == "Secret"
                and body["metadata"].get("labels", {}).get("datalabs.pkg.internal/connection")}

    def scenario(xr):
        name = xr["metadata"]["name"]
        runtime = {
            "apiVersion": "kubernetes.m.crossplane.io/v1alpha1", "kind": "Object",
            "metadata": {"name": "workshopenvironment-" + name, "namespace": "teams",
                         "annotations": {"crossplane.io/composition-resource-name": "workshopenvironment-" + name}},
            "status": {"atProvider": {"manifest": {"status": {"educates": {"namespace": name + "-runtime"}}}}},
        }
        initial = run(xr, env, [runtime])
        assert len(connections(initial)) == 3 and not any(c["ready"] for c in connections(initial))
        assert not copies(initial)
        observed = [runtime]
        for key, body in initial.items():
            spec = body.get("spec", {})
            manifest = spec.get("forProvider", {}).get("manifest", {})
            if spec.get("managementPolicies") != ["Observe"] or manifest.get("metadata", {}).get("name") not in values:
                continue
            assert manifest["metadata"]["namespace"] == name + "-runtime"
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
    assert len(published) == 4 and not any(c["ready"] for c in connections(pending))
    expected = {
        "postgres": encoded({key: value for key, value in values["prod-pguser-postgres"].items() if key not in ("verifier", "jdbc-uri")}),
        "mongo": encoded({"user": "prod-app", "password": "test-mongo-password"}),
        "redis": encoded({"user": "default", "password": "test-redis-password"}),
        "custom": encoded(values["apikey"]),
    }
    for connection in connections(pending):
        ref = connection["secretRef"]
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
        custom_source = next(body for body in typed_sources[1:]
                             if body["status"]["atProvider"]["manifest"]["metadata"]["name"] == "apikey")
        custom_source["status"]["atProvider"]["manifest"].update(type=secret_type, data=encoded(fields))
        typed = run(source, env, typed_sources)
        ref = next(c["secretRef"] for c in connections(typed) if c["type"] == "custom")
        copy = next(body for body in copies(typed).values() if body["metadata"]["name"] == ref["name"])
        assert copy["type"] == expected_type and copy["data"] == encoded(fields)
    print("PASS custom connection copies preserve usable Secret types without binding copied account tokens")

    rotated = deepcopy(observed)
    for body in rotated[1:]:
        data = body["status"]["atProvider"]["manifest"]["data"]
        key = "token" if "token" in data else "password"
        data[key] = encoded({key: "test-rotated"})[key]
        if "uri" in data:
            data["uri"] = encoded({"uri": "postgresql://postgres:test-rotated@prod/app"})["uri"]
    rotating = run(source, env, [*rotated, *published.values()])
    assert not any(c["ready"] for c in connections(rotating))
    current = copies(rotating)
    assert set(current) == set(published)
    assert all(current[key]["data"] != published[key]["data"] for key in current)
    assert all(c["ready"] for c in connections(run(source, env, [*rotated, *current.values()])))
    print("PASS rotation updates stable copies and withholds readiness until every credential matches")

    unavailable = deepcopy(rotated)
    for body in unavailable[1:]:
        body["status"]["conditions"][1].update(status="False", message="observe failed: external resource does not exist")
    stale = deepcopy(source)
    stale["status"] = deepcopy(ready["composite"]["status"])
    lost = run(stale, env, [*unavailable, *current.values()])
    assert not copies(lost)
    assert len(connections(lost)) == 3 and not any(c["ready"] for c in connections(lost))
    assert all(body["spec"]["managementPolicies"] == ["Observe"] for body in observed[1:])
    restored = run(source, env, [*rotated, *current.values()])
    assert all(c["ready"] for c in connections(restored))
    print("PASS unavailable sources remove stale copies and readiness; recovery republishes current credentials")

    incomplete = deepcopy(observed)
    postgres = next(body for body in incomplete[1:]
                    if body["status"]["atProvider"]["manifest"]["metadata"]["name"] == "prod-pguser-postgres")
    postgres["status"]["atProvider"]["manifest"]["data"].pop("password")
    missing = run(source, env, [*incomplete, *published.values()])
    assert not next(c["ready"] for c in connections(missing) if c["type"] == "postgres")
    assert len(copies(missing)) == 3
    print("PASS incomplete credentials cannot produce a ready connection")

    for kind, secret_name in (("mongo", "prod-mongodb-auth"), ("redis", "prod-redis-auth")):
        incomplete = deepcopy(observed)
        credential = next(body for body in incomplete[1:]
                          if body["status"]["atProvider"]["manifest"]["metadata"]["name"] == secret_name)
        credential["status"]["atProvider"]["manifest"]["data"].pop("user")
        missing = run(source, env, [*incomplete, *published.values()])
        assert not next(c["ready"] for c in connections(missing) if c["type"] == kind)
        assert len(copies(missing)) == 3
    print("PASS MongoDB and Redis publication waits for both user and password")

    other = deepcopy(source)
    other["metadata"].update(name="s-john", uid="test-other-datalab")
    other_sources = scenario(other)
    for body in other_sources[1:]:
        data = body["status"]["atProvider"]["manifest"]["data"]
        field = "token" if "token" in data else "password"
        data[field] = encoded({field: "test-john-credential"})[field]
    separate = run(other, env, other_sources)
    assert {c["secretRef"]["name"] for c in connections(pending)}.isdisjoint(
        c["secretRef"]["name"] for c in connections(separate))
    assert len({c["secretRef"]["name"] for c in connections(pending)}) == 4
    assert all(encoded({"value": "test-john-credential"})["value"] in body["data"].values()
               for body in copies(separate).values())
    print("PASS identical service instance names stay distinct across service types and Datalabs")

    removed = deepcopy(stale)
    removed["spec"].update(databases={}, documentStores={}, cacheStores={})
    retired_env = deepcopy(env)
    retired_env["data"]["customSecrets"] = []
    retired = run(removed, retired_env, [*observed, *published.values()])
    assert not copies(retired) and not connections(retired)
    print("PASS service removal drops publication resources and stale references for Crossplane cleanup")


if __name__ == "__main__":
    main()
