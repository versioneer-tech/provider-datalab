# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from copy import deepcopy
import json
from crossplane.function import request, response
from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from composition.helpers import _resource_name, _to_dict, _vcluster_cleanup_generation
from composition.render import _render_template

CLEANUP_SCRIPT = _embedded_script("scripts/vcluster-cleanup.py")


def _manifest(resource):
    state = resource.get("status", {}).get("atProvider", {})
    return state.get("manifest") or state.get("raw", {}).get("manifest") or {}


def _condition(resource, kind):
    return any(c.get("type") == kind and c.get("status") == "True"
               for c in resource.get("status", {}).get("conditions", []))


def compose(req, rsp):
    xr = _to_dict(req.observed.composite.resource)
    status = _to_dict(rsp.desired.composite.resource).get("status") or {}
    previous = {item["name"]: item for item in (xr.get("status") or {}).get("vclusters", [])}
    observed = {key: _to_dict(value.resource) for key, value in req.observed.resources.items()}
    env = _to_dict(req.context).get("apiextensions.crossplane.io/environment") or {}
    meta = xr["metadata"]
    name, claim_namespace = meta["name"], meta.get("namespace", "default")
    states = []
    active = set((xr.get("spec", {}).get("vclusters") or {}))
    for key, body in observed.items():
        instance = body.get("metadata", {}).get("labels", {}).get("datalabs.versioneer.at/vcluster")
        if (instance and instance not in active
                and body.get("spec", {}).get("providerConfigRef", {}).get("name") == _resource_name(name, "vcluster", instance)
                and body.get("metadata", {}).get("annotations", {}).get("crossplane.io/paused") == "true"):
            # Release an old paused record before omission asks Crossplane to delete it.
            kept = {field: deepcopy(body[field]) for field in ("apiVersion", "kind", "spec", "metadata")}
            kept["metadata"] = {field: kept["metadata"][field]
                                for field in ("name", "namespace", "annotations", "labels") if field in kept["metadata"]}
            kept["metadata"]["annotations"]["crossplane.io/paused"] = "false"
            kept["spec"]["managementPolicies"] = ["Observe"]
            rsp.desired.resources[key].resource.update(kept)
            rsp.desired.resources[key].ready = fnv1.READY_TRUE
    for instance, config in sorted((xr.get("spec", {}).get("vclusters") or {}).items()):
        runtime = _resource_name("vcluster", instance, limit=45)
        virtual_provider = _resource_name(name, "vcluster", instance)
        control_key = _resource_name("vcluster", name, instance, "statefulset")
        if control_key not in rsp.desired.resources:
            continue
        control_ready = (_condition(observed.get(control_key, {}), "Ready") and
                         rsp.desired.resources[control_key].resource["spec"]["forProvider"]["manifest"]["spec"]["replicas"] == 1)
        hibernated = config.get("hibernated", False)
        cleanup_generation = _vcluster_cleanup_generation(req, instance, hibernated)
        lifecycle_name = _resource_name("vc-cleanup", instance, limit=45)
        job_name = _resource_name(lifecycle_name, str(cleanup_generation))
        jobs = {
            body["spec"]["forProvider"]["manifest"]["metadata"]["name"]: (key, body)
            for key, body in observed.items()
            if body.get("metadata", {}).get("labels", {}).get("datalabs.versioneer.at/vcluster") == instance
            and body.get("metadata", {}).get("labels", {}).get("datalabs.versioneer.at/lifecycle") == "cleanup"
        }
        retained = previous.get(instance, {}).get("cleanupJob")
        if retained and retained not in jobs:
            jobs[retained] = (_resource_name("vcluster", name, instance, retained), {})
        if hibernated and job_name not in jobs:
            jobs[job_name] = (_resource_name("vcluster", name, instance, job_name), {})
        blocked, complete, failure = False, False, ""

        def emit(suffix, manifest):
            key = _resource_name("vcluster", name, instance, suffix)
            rsp.desired.resources[key].resource.update(_render_template(
                req, "common/object", key=key, xr_namespace=claim_namespace,
                manifest=manifest, readiness={"policy": "SuccessfulCreate"},
            ))
            rsp.desired.resources[key].resource["metadata"]["labels"] = {
                "datalabs.versioneer.at/vcluster": instance,
            }
            return key

        if jobs:
            values = {
                "namespace": name, "runtime": runtime, "lifecycle_name": lifecycle_name,
                "cleanup_script": CLEANUP_SCRIPT,
                "cleanup_policy": _resource_name(name, instance, "cleanup-pods"),
                "cleanup_identity_expression": f"request.userInfo.username == {json.dumps(f'system:serviceaccount:{name}:{lifecycle_name}')}",
            }
            support = _render_template(req, "vcluster/cleanup-support", **values)["resources"]
            support_keys = []
            for suffix, manifest in support.items():
                support_keys.append(emit(f"cleanup-{suffix}", manifest))
            support_ready = all(_condition(observed.get(key, {}), "Ready") for key in support_keys)
            for current_name, (key, body) in sorted(jobs.items()):
                running = hibernated and current_name == job_name
                host_job = _manifest(body)
                if not host_job.get("metadata", {}).get("uid"):
                    requirement = _resource_name(key, "job")
                    response.require_resources(
                        rsp, name=requirement, api_version="batch/v1", kind="Job",
                        namespace=name, match_name=current_name,
                    )
                    host_job = request.get_required_resource(req, requirement) or {}
                uid = host_job.get("metadata", {}).get("uid")
                pods_known, stopped = False, False
                if uid:
                    requirement = _resource_name(key, "pods")
                    response.require_resources(
                        rsp, name=requirement, api_version="v1", kind="Pod",
                        namespace=name, match_labels={"batch.kubernetes.io/controller-uid": uid},
                    )
                    pods_known = requirement in req.required_resources
                    pods = request.get_required_resources(req, requirement)
                    # A suspended Job may still have a Pod in its termination grace period.
                    stopped = pods_known and all(
                        pod.get("status", {}).get("phase") in ("Succeeded", "Failed")
                        for pod in pods
                        if any(o.get("uid") == uid and o.get("kind") == "Job"
                               for o in pod.get("metadata", {}).get("ownerReferences", []))
                    )
                terminal = _condition(host_job, "Complete") or _condition(host_job, "Failed")
                suspended = host_job.get("spec", {}).get("suspend") is True and _condition(host_job, "Suspended")
                safe = stopped and (terminal or suspended)
                if running:
                    complete = stopped and _condition(host_job, "Complete")
                    if _condition(host_job, "Failed"):
                        failure = f"Cleanup Job {current_name} failed; inspect its status and Pod logs."
                elif not safe:
                    blocked = True
                if not running and safe:
                    continue
                manifest = deepcopy(body.get("spec", {}).get("forProvider", {}).get("manifest"))
                if not manifest and host_job:
                    # Recover the immutable template if the Object observation was lost.
                    manifest = {"apiVersion": "batch/v1", "kind": "Job",
                                "metadata": {"name": current_name, "namespace": name},
                                "spec": deepcopy(host_job["spec"])}
                if not manifest:
                    manifest = _render_template(
                        req, "vcluster/cleanup-job", **values, job_name=current_name,
                        suspended=not running,
                        cleanup_generation=str(int(cleanup_generation if running
                                                   else previous.get(instance, {}).get("cleanupGeneration", 0))),
                        cleanup_image=(env.get("images") or {}).get("vclusterCleanup") or "python:3.13-alpine@sha256:9ef1a599f863231c3d91e941389bfdc4a2d6070557243d54df1a4e57015b960e",
                    )
                    placement = ((env.get("vcluster") or {}).get("scheduling") or {}).get("controlPlane") or {}
                    manifest["spec"]["template"]["spec"].update(placement)
                manifest["spec"]["suspend"] = not (running and support_ready)
                emit(current_name, manifest)
                rsp.desired.resources[key].resource["spec"]["references"] = [
                    {"dependsOn": {"name": _resource_name("vcluster", name, instance, f"cleanup-{suffix}"), "namespace": claim_namespace}}
                    for suffix in ("account", "script", "binding", "policy", "policy-binding")
                ]
                rsp.desired.resources[key].resource["metadata"]["labels"]["datalabs.versioneer.at/lifecycle"] = "cleanup"
                rsp.desired.resources[key].ready = fnv1.READY_TRUE if complete else fnv1.READY_FALSE

        state = {"name": instance, "phase": "Running" if control_ready else "Starting",
                 "message": "Control plane is ready." if control_ready else "Waiting for the control plane.",
                 "observedGeneration": int(meta.get("generation", 1))}
        if hibernated:
            state.update(phase="Failed" if failure else ("Hibernated" if complete and not blocked else "Hibernating"),
                         message=failure or ("Control plane and synced host Pods are gone." if complete and not blocked
                                             else "Waiting for control-plane shutdown and host Pod cleanup."),
                         cleanupJob=job_name, cleanupGeneration=cleanup_generation)
            rsp.desired.resources[control_key].ready = (
                fnv1.READY_TRUE if state["phase"] == "Hibernated" else fnv1.READY_FALSE
            )
        elif blocked:
            state.update(phase="Resuming", message="Waiting for old cleanup Jobs and their Pods to stop.")
            if retained:
                state["cleanupJob"] = retained
                state["cleanupGeneration"] = int(previous[instance].get("cleanupGeneration", 0))
            rsp.desired.resources[control_key].resource["spec"]["forProvider"]["manifest"]["spec"]["replicas"] = 0
            rsp.desired.resources[control_key].ready = fnv1.READY_FALSE

        offline = hibernated or blocked or not control_ready
        if offline:
            # Keep removals queued while the virtual API cannot process finalizers.
            for key, body in observed.items():
                if (body.get("spec", {}).get("providerConfigRef", {}).get("name") == virtual_provider
                        and key not in rsp.desired.resources):
                    kept = {field: deepcopy(body[field]) for field in ("apiVersion", "kind", "spec")}
                    kept["metadata"] = {field: deepcopy(body["metadata"][field])
                                        for field in ("name", "namespace", "annotations", "labels")
                                        if field in body["metadata"]}
                    rsp.desired.resources[key].resource.update(kept)
            for desired in rsp.desired.resources.values():
                body = _to_dict(desired.resource)
                if body.get("spec", {}).get("providerConfigRef", {}).get("name") == virtual_provider:
                    # Observe-only keeps offline records deletable without the virtual API.
                    body["metadata"].setdefault("annotations", {})["crossplane.io/paused"] = "false"
                    body["spec"]["managementPolicies"] = ["Observe"]
                    desired.resource.update({"metadata": body["metadata"], "spec": body["spec"]})
                    desired.ready = fnv1.READY_TRUE
        states.append(state)
    if states or previous:
        status["vclusters"] = states
        rsp.desired.composite.resource.update({"status": status})
