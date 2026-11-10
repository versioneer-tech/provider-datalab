# Run a sandbox

Each virtual cluster installs Agent Sandbox CRDs and its controller. A
`sandboxd` SandboxTemplate is available in `default`, configured profile
namespaces, and session namespaces. The start script copies its Pod settings
into a Sandbox. The controller starts the Pod, where sandboxd provides a
file API over HTTP and command execution over gRPC.

This guide creates a Sandbox, connects to both APIs from your computer, and
checks that a file survives workload replacement. Run the commands from the
repository checkout with Bash, `kubectl`, `jq`, `curl`, Python 3, and
[grpcurl](https://github.com/fullstorydev/grpcurl#installation) installed.

## 1. Declare session storage

Add a session to your existing Datalab manifest. Keep its other settings:

```yaml
spec:
  vclusters:
    vc0: {}
  sessions:
  - name: analysis
    vcluster: vc0
    namespace: demo
    pvcSize: 2Gi
```

Apply the updated Datalab through your usual host-cluster or GitOps process.
The provider creates PVC `demo/session-analysis` in `vc0`. Without `pvcSize`,
it uses `defaults.session.pvcSize`, or `1Gi`. The PVC uses the virtual cluster's
default allowed StorageClass. `status.sessions` reports its name and namespace.
A PVC with delayed binding stays Pending until a workload mounts it.

Declaring a session creates storage; it does not start a Sandbox. A session
cannot move between virtual clusters or namespaces.

## 2. Connect to the virtual cluster

[Download a virtual kubeconfig and sign in](vcluster.md#human-access). This
walkthrough uses the built-in `cluster-admin` profile and an authorized Datalab
administrator. A namespace role also works if it grants access to Sandboxes,
SandboxTemplates, Pods, port-forwarding, and PVCs in `demo`.

Set the path to your downloaded file. These commands use only that virtual
cluster:

```bash
sandbox_kubeconfig="$PWD/s-joe-vc0.kubeconfig"
sandbox_context="$(kubectl --kubeconfig "$sandbox_kubeconfig" config current-context)"
kube=(kubectl --kubeconfig "$sandbox_kubeconfig" --context "$sandbox_context" --namespace demo)

"${kube[@]}" get sandboxtemplate.extensions.agents.x-k8s.io/sandboxd
"${kube[@]}" get pvc/session-analysis
```

The first authenticated command can open the device-login flow. The kubeconfig
selects an endpoint; your user's roles determine access.

## 3. Start the Sandbox

Run the [start script](../examples/start-sandbox.sh):

```bash
bash docs/examples/start-sandbox.sh \
  "$sandbox_kubeconfig" "$sandbox_context" demo analysis session-analysis
```

The script reads the installed sandboxd template, mounts the session PVC at
`/workspace`, creates Sandbox `analysis`, and waits for it to become Ready.
It uses the image and resource settings from the installed template. It fails
if that Sandbox name already exists.

The [Sandbox manifest](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/vcluster/sandbox.yaml)
is an alternative for users who need to change the Pod settings. Use it in
place of the start script. Its image is fixed in the example; the script uses
the installed template, including any `images.sandboxd` override.

## 4. Forward the sandboxd ports

In the same terminal, run:

```bash
"${kube[@]}" port-forward --address 127.0.0.1 pod/analysis 18080:8080 19090:9090
```

Leave this command running. Local port `18080` reaches the HTTP file API and
health endpoint. Local port `19090` reaches the gRPC command API. Kubernetes
authenticates and authorizes the connection.

## 5. Check files and commands from your computer

In a second terminal, run the [check script](../examples/check-sandbox.sh) from
the same checkout:

```bash
bash docs/examples/check-sandbox.sh write 18080 19090
```

It checks sandboxd health, writes `manual-check.txt` through the HTTP API,
reads it back, and runs `cat /workspace/manual-check.txt` through gRPC.
All three checks must print `PASS`. The script uses the same
[command protocol](https://github.com/versioneer-tech/provider-datalab/blob/main/tests/vcluster/process.proto)
as the integration test. It needs no gRPC server reflection.

You can also call the HTTP endpoints directly:

```bash
curl --fail http://127.0.0.1:18080/v1/health
curl --fail --request PUT --header 'Content-Type: application/octet-stream' \
  --data-binary 'sandbox check from local' \
  http://127.0.0.1:18080/v1/files/manual-check.txt
curl --fail http://127.0.0.1:18080/v1/files/manual-check.txt
```

Commands execute in the sandboxd container. Set
`EnvironmentConfig.data.images.sandboxd` to use a compatible image with
additional tools. The image must start sandboxd. Set `data.images.sandbox`
to change the Agent Sandbox controller image. See
[service images](installation.md#service-images) for the default tags.

## 6. Check persistence after replacement

In the first terminal, press Ctrl-C to stop port-forwarding. Record the PVC
identity, delete the Sandbox, and wait for its Pod to disappear:

```bash
pvc_uid="$("${kube[@]}" get pvc/session-analysis -o jsonpath='{.metadata.uid}')"
"${kube[@]}" delete sandbox.agents.x-k8s.io/analysis --wait=true
"${kube[@]}" wait pod/analysis --for=delete --timeout=5m

bash docs/examples/start-sandbox.sh \
  "$sandbox_kubeconfig" "$sandbox_context" demo analysis session-analysis

test "$pvc_uid" = "$("${kube[@]}" get pvc/session-analysis -o jsonpath='{.metadata.uid}')" \
  && printf 'PASS session PVC UID\n'
"${kube[@]}" port-forward --address 127.0.0.1 pod/analysis 18080:8080 19090:9090
```

In the second terminal, check the saved file without writing it again:

```bash
bash docs/examples/check-sandbox.sh read 18080 19090
```

The UID check must print `PASS session PVC UID`. The REST and gRPC checks
must return the original file content. These checks confirm that the new
workload uses the same storage.

## Stop and remove

Stop port-forwarding with Ctrl-C. Delete the Sandbox to stop its workload:

```bash
"${kube[@]}" delete sandbox.agents.x-k8s.io/analysis --wait=true
"${kube[@]}" wait pod/analysis --for=delete --timeout=5m
"${kube[@]}" get pvc/session-analysis
```

The session PVC remains. Remove the session entry from the Datalab only when
you intend to delete its storage, after all workloads that mount it have
stopped. Back up data before removing a session, virtual cluster, or Datalab.

## Use a SandboxClaim

For a workload that does not need a declared session PVC, create a claim in a
namespace with the sandboxd template:

```yaml
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxClaim
metadata:
  name: task
  namespace: demo
spec:
  sandboxTemplateRef:
    name: sandboxd
```

Agent Sandbox creates the workload and a separate workspace PVC from the
template. Its controller manages that PVC's lifetime. Use a declared session
PVC when files must remain independent of the workload's lifetime.

## If a check fails

Inspect the Sandbox, Pod events, and runtime logs:

```bash
"${kube[@]}" describe sandbox.agents.x-k8s.io/analysis
"${kube[@]}" describe pod/analysis
"${kube[@]}" logs pod/analysis -c sandboxd
```

A Forbidden response requires the correct user role. A Pending PVC or Pod can
indicate a storage, scheduling, or host quota limit. The host quota includes
services, virtual control planes, and workloads across the whole Datalab.
If a local port is in use, choose another port in both the forwarding command
and the check script.

Sandbox workloads use the [host namespace network policies](../security/sandbox-controls.md).
All virtual clusters in one Datalab share the team boundary. Configure backend
access in EnvironmentConfig.

See the upstream [installation guide](https://agent-sandbox.sigs.k8s.io/docs/getting_started/install_prerequisites/)
and [runtime API](https://agent-sandbox.sigs.k8s.io/docs/api/runtime/) for other
clients and runtime APIs.
