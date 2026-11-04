# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check session discovery and removal of stale runtime details."""

from copy import deepcopy

from render import arguments, environment, manifest, render


def main():
    args = arguments()
    source = {
        "apiVersion": "pkg.internal/v1beta2",
        "kind": "Datalab",
        "metadata": {"name": "test-sessions", "namespace": "workspace"},
        "spec": {"sessions": [{"name": "work"}, {"name": "saved", "state": "stopped"}]},
        "status": {"sessions": {"retired": {"state": "started", "url": "https://old.example"}}},
    }
    env = environment()
    initial = render(args, env, source, [], include_composite=True)
    expected = [
        {"name": name, "state": state,
         "pvcRef": {"name": f"test-sessions-{name}-persistent", "namespace": "test-sessions"}}
        for name, state in (("work", "started"), ("saved", "stopped"))
    ]
    assert initial["composite"]["status"]["sessions"] == expected

    def observed_object(key, status):
        body = deepcopy(initial[key])
        body["status"] = {"atProvider": {"manifest": {"status": status}}}
        return body

    observed = [observed_object("workshopenvironment-test-sessions", {
        "educates": {"namespace": "test-runtime"}
    })]
    for name in ("work", "saved"):
        runtime = observed_object("workshopsession-test-sessions-work", {
            "educates": {"phase": "Running", "message": "Ready", "url": f"https://{name}.example"}
        })
        runtime["metadata"]["annotations"]["crossplane.io/composition-resource-name"] = f"workshopsession-test-sessions-{name}"
        runtime["metadata"]["name"] = f"workshopsession-test-sessions-{name}"
        observed.append(runtime)
    running = render(args, env, source, observed, include_composite=True)
    for entry in expected:
        entry["pvcRef"]["namespace"] = "test-runtime"
        pvc = manifest(running, f"persistentvolumeclaim-test-sessions-{entry['name']}-persistent")
        assert entry["pvcRef"] == {key: pvc["metadata"][key] for key in ("name", "namespace")}
    expected[0].update(phase="Running", message="Ready", url="https://work.example")
    assert running["composite"]["status"]["sessions"] == expected

    stopped = deepcopy(source)
    stopped["status"] = running["composite"]["status"]
    stopped["spec"]["sessions"] = [{"name": "work", "state": "stopped"}]
    result = render(args, env, stopped, observed, include_composite=True)
    assert result["composite"]["status"]["sessions"] == [{
        "name": "work", "state": "stopped", "pvcRef": expected[0]["pvcRef"]
    }]
    assert "workshopsession-test-sessions-work" not in result
    stopped["spec"]["sessions"] = []
    result = render(args, env, stopped, observed, include_composite=True)
    assert not result["composite"].get("status", {}).get("sessions")
    print("PASS session names and PVC references survive stopping; stale runtime details and removed sessions do not")


if __name__ == "__main__":
    main()
