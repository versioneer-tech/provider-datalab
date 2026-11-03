# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check approved delivery, rotation, denial, and removal of virtual Secrets."""

import base64
from copy import deepcopy

from render import arguments, environment, manifest, render


def observed(body, external=None):
    value = deepcopy(body)
    value["status"] = {
        "atProvider": {"manifest": external or body["spec"]["forProvider"]["manifest"]},
        "conditions": [{"type": "Ready", "status": "True"}],
    }
    return value


def main():
    args = arguments()
    env = environment()
    env["data"]["defaults"] = {"data": {"enabled": False}}
    env["data"]["vcluster"] = {"storageClasses": {"allowed": ["standard"]}}
    grant = {
        "secretRef": {"namespace": "shared-secrets", "name": "analytics-reader"},
        "keys": ["url", "binary"],
        "targets": [
            {
                "claimNamespace": "workspace",
                "datalab": "team",
                "instance": "vc0",
                "namespace": "demo",
            }
        ],
    }
    env["data"]["secretExports"] = {"analytics-reader": grant}
    binding = {
        "export": "analytics-reader",
        "target": {"namespace": "demo", "name": "catalog-database"},
        "keys": {"url": "DATABASE_URL", "binary": "certificate"},
    }
    source = {
        "apiVersion": "pkg.internal/v1",
        "kind": "Datalab",
        "metadata": {"name": "team", "namespace": "workspace", "uid": "test-team"},
        "spec": {
            "users": [],
            "vclusters": {
                instance: {
                    "groups": [{"name": "readers", "namespace": "demo", "role": "view"}]
                }
                for instance in ("vc0", "vc1")
            },
        },
    }
    source["spec"]["vclusters"]["vc0"]["secretBindings"] = {"catalog": binding}

    def run(config=source, settings=env, resources=None):
        return render(args, settings, config, resources or [], include_composite=True)

    def state(resources):
        return resources["composite"]["status"]["secretBindings"][0]

    empty = run()
    assert state(empty)["reason"] == "SourceNotReady"
    source_key = next(
        key
        for key, body in empty.items()
        if body.get("spec", {}).get("managementPolicies") == ["Observe"]
        and body["spec"]["forProvider"]["manifest"].get("metadata", {}).get("namespace")
        == "shared-secrets"
    )
    observer = empty[source_key]
    assert observer["spec"]["providerConfigRef"]["name"] == "provider-kubernetes"
    assert observer["spec"]["forProvider"]["manifest"]["metadata"] == grant["secretRef"]
    assert "data" not in observer["spec"]["forProvider"]["manifest"]
    data = {
        "url": base64.b64encode(b"postgresql://reader@analytics/db").decode(),
        "binary": base64.b64encode(b"\xff\x00").decode(),
        "unapproved": base64.b64encode(b"not-exported").decode(),
    }
    host = observed(
        observer,
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": grant["secretRef"],
            "data": data,
        },
    )
    waiting = run(resources=[host])
    assert state(waiting)["reason"] == "ProtectionNotReady"
    policies = [
        observed(body)
        for body in waiting.values()
        if body.get("spec", {}).get("forProvider", {}).get("manifest", {}).get("kind")
        in ("ValidatingAdmissionPolicy", "ValidatingAdmissionPolicyBinding")
        and "secret-binding" in body["metadata"]["name"]
    ]
    assert len(policies) == 2
    delivered = run(resources=[host, *policies])
    target_key = next(
        key
        for key, body in delivered.items()
        if body.get("spec", {})
        .get("forProvider", {})
        .get("manifest", {})
        .get("metadata", {})
        .get("name")
        == "catalog-database"
    )
    target = delivered[target_key]
    target_manifest = manifest(delivered, target_key)
    assert target_manifest["data"] == {
        "DATABASE_URL": data["url"],
        "certificate": data["binary"],
    }
    assert target_manifest["metadata"]["namespace"] == "demo"
    providers = {
        body["metadata"]["labels"]["datalabs.pkg.internal/vcluster"]: body["spec"][
            "providerConfigRef"
        ]["name"]
        for body in empty.values()
        if body.get("spec", {}).get("forProvider", {}).get("manifest", {}).get("kind")
        == "Namespace"
        and body["spec"]["forProvider"]["manifest"]["metadata"]["name"] == "demo"
    }
    assert target["spec"]["providerConfigRef"]["name"] == providers["vc0"]
    assert target["spec"]["providerConfigRef"]["name"] != providers["vc1"]
    assert not state(delivered)["ready"]
    current_target = observed(target)
    current = run(resources=[host, *policies, current_target])
    assert state(current)["ready"]
    assert set(state(current)) == {
        "name",
        "instance",
        "export",
        "target",
        "ready",
        "reason",
    }
    print(
        "PASS approved host Secret is read without writes and selected binary keys reach only its virtual namespace",
        flush=True,
    )

    alias_source, alias_env = deepcopy(source), deepcopy(env)
    alias_source["spec"]["vclusters"]["vc0"]["secretBindings"]["catalog"]["export"] = (
        "another-alias"
    )
    alias_env["data"]["secretExports"]["another-alias"] = deepcopy(grant)
    same = run(alias_source, alias_env, [host, *policies, current_target])
    assert state(same)["ready"] and target_key in same
    renamed = deepcopy(source)
    renamed["spec"]["vclusters"]["vc0"]["secretBindings"]["renamed"] = renamed["spec"][
        "vclusters"
    ]["vc0"]["secretBindings"].pop("catalog")
    replacing = run(renamed, env, [host, *policies, current_target])
    assert state(replacing)["reason"] == "ReplacingTarget"
    assert target_key not in replacing
    assert not any(
        "secret-binding" in key
        and body.get("spec", {}).get("forProvider", {}).get("manifest", {}).get("kind")
        in ("ValidatingAdmissionPolicy", "ValidatingAdmissionPolicyBinding")
        for key, body in replacing.items()
    )
    print(
        "PASS equivalent aliases keep the target and binding replacement waits for old target cleanup",
        flush=True,
    )

    rotated = deepcopy(host)
    rotated["status"]["atProvider"]["manifest"]["data"]["url"] = base64.b64encode(
        b"postgresql://rotated@analytics/db"
    ).decode()
    updated = run(resources=[rotated, *policies, current_target])
    assert not state(updated)["ready"]
    assert (
        manifest(updated, target_key)["data"]["DATABASE_URL"]
        != target_manifest["data"]["DATABASE_URL"]
    )
    settled = run(resources=[rotated, *policies, observed(updated[target_key])])
    assert state(settled)["ready"]
    assert settled[source_key]["spec"] == observer["spec"]
    print("PASS source rotation updates the target before reporting ready", flush=True)

    namespace_source, namespace_env = deepcopy(source), deepcopy(env)
    namespace_source["spec"]["vclusters"]["vc0"]["secretBindings"]["catalog"]["target"][
        "namespace"
    ] = "catalog"
    namespace_env["data"]["secretExports"]["analytics-reader"]["targets"][0][
        "namespace"
    ] = "catalog"
    namespace_result = run(namespace_source, namespace_env)
    created = [
        body
        for body in namespace_result.values()
        if body.get("spec", {}).get("forProvider", {}).get("manifest", {}).get("kind")
        == "Namespace"
        and body["spec"]["forProvider"]["manifest"]["metadata"]["name"] == "catalog"
    ]
    assert len(created) == 1
    assert created[0]["spec"]["managementPolicies"] == ["Observe", "Create", "Update"]
    print(
        "PASS an approved binding creates its virtual namespace without deleting it on removal",
        flush=True,
    )

    for change in ("export", "namespace", "instance", "key", "claim", "duplicate", "duplicate-key"):
        denied_source, denied_env = deepcopy(source), deepcopy(env)
        requested = denied_source["spec"]["vclusters"]["vc0"]["secretBindings"][
            "catalog"
        ]
        if change == "export":
            requested["export"] = "unapproved"
        elif change == "namespace":
            requested["target"]["namespace"] = "other"
        elif change == "instance":
            denied_source["spec"]["vclusters"]["vc1"]["secretBindings"] = denied_source[
                "spec"
            ]["vclusters"]["vc0"].pop("secretBindings")
        elif change == "key":
            requested["keys"]["unapproved"] = "password"
        elif change == "claim":
            denied_source["metadata"]["namespace"] = "other-claim"
        elif change == "duplicate-key":
            requested["keys"]["binary"] = "DATABASE_URL"
        else:
            denied_source["spec"]["vclusters"]["vc0"]["secretBindings"]["duplicate"] = (
                deepcopy(requested)
            )
        result = run(denied_source, denied_env)
        assert all(
            item["reason"] == "Denied"
            for item in result["composite"]["status"]["secretBindings"]
        ), change
        assert not any("secret-binding" in key for key in result), change
    print(
        "PASS unapproved sources, destinations, claims, keys, and duplicate targets read no host Secrets",
        flush=True,
    )

    switched_env = deepcopy(env)
    switched_env["data"]["secretExports"]["analytics-reader"]["secretRef"]["name"] = (
        "another-reader"
    )
    switched = run(settings=switched_env, resources=[host, *policies, current_target])
    assert not state(switched)["ready"]
    assert source_key not in switched
    assert state(switched)["reason"] == "SourceNotReady"
    print(
        "PASS replacing an approved source does not reuse the previous observer",
        flush=True,
    )

    for missing in (True, False):
        absent = deepcopy(host)
        absent["status"]["atProvider"]["manifest"]["data"] = (
            {} if missing else {"unapproved": data["unapproved"]}
        )
        pending = run(resources=[absent, *policies])
        assert target_key not in pending
        assert not state(pending)["ready"]
    outage = run(resources=[*policies, current_target])
    assert target_key in outage and not state(outage)["ready"]
    unmanaged = deepcopy(current_target)
    unmanaged["status"]["atProvider"]["manifest"]["metadata"].pop("labels")
    conflict = run(resources=[host, *policies, unmanaged])
    assert state(conflict)["reason"] == "TargetConflict"
    assert conflict[target_key]["spec"]["managementPolicies"] == ["Observe"]
    assert "data" not in manifest(conflict, target_key)
    print(
        "PASS missing data creates no empty Secret, source outages keep the managed copy, and target conflicts stop writes",
        flush=True,
    )

    for revoke in (True, False):
        reduced_source, reduced_env = deepcopy(source), deepcopy(env)
        if revoke:
            reduced_env["data"]["secretExports"] = {}
        else:
            reduced_source["spec"]["vclusters"]["vc0"]["secretBindings"] = {}
        reduced = run(reduced_source, reduced_env, [host, *policies, current_target])
        assert target_key not in reduced and source_key not in reduced
        assert "vcluster-team-vc1-statefulset" in reduced
        if not revoke:
            assert reduced["composite"]["status"]["secretBindings"] == []
    print(
        "PASS revocation and binding removal remove the target without changing the other instance",
        flush=True,
    )

    service_env = deepcopy(env)
    service_env["data"]["secretExports"]["analytics-reader"] = {
        **grant,
        "connection": "s3",
    }
    del service_env["data"]["secretExports"]["analytics-reader"]["secretRef"]
    service_env["data"]["secretExports"]["analytics-reader"]["keys"] = ["AWS_REGION"]
    service_source = deepcopy(source)
    service_source["spec"]["vclusters"]["vc0"]["secretBindings"]["catalog"]["keys"] = {
        "AWS_REGION": "region"
    }
    # The published source is independently generated from its storage observer.
    storage = deepcopy(host)
    storage["metadata"]["name"] = "observe-storage-secret-team"
    storage["metadata"]["annotations"]["crossplane.io/composition-resource-name"] = (
        "observe-storage-secret-team"
    )
    storage["status"]["atProvider"]["manifest"]["data"] = {
        key: base64.b64encode(value.encode()).decode()
        for key, value in {
            "AWS_ACCESS_KEY_ID": "test-access",
            "AWS_SECRET_ACCESS_KEY": "test-secret",
            "AWS_REGION": "test-region",
        }.items()
    }
    local = run(service_source, service_env, [storage])
    assert "connection-team-s3" in local
    assert not any(
        body.get("spec", {})
        .get("forProvider", {})
        .get("manifest", {})
        .get("metadata", {})
        .get("namespace")
        == "shared-secrets"
        for body in local.values()
    )
    assert state(local)["reason"] == "ProtectionNotReady"
    print(
        "PASS an approved Datalab connection uses its separate output without an aggregate Secret",
        flush=True,
    )


if __name__ == "__main__":
    main()
