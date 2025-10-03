# Provider Datalab – Usage & Concepts

This section explains how to **use** the `provider-datalab` configuration packages once they are installed. It focuses on the **concepts** of Sessions, Files, vclusters, Storage Secrets, and the required **Keycloak integration** for identity and access.

---

## Concepts

### Sessions
A `Datalab` claim may declare one or more `spec.sessions`.  

- If at least one session is listed, a corresponding **WorkshopSession** is automatically created and will run permanently until stopped by the operator.  
- If no sessions are given, no runtime will be started; users must explicitly launch a session themselves (`auto` mode).  

Sessions can also be patched into the spec later if needed.

### Files and the Workshop Tab
The `spec.files` array is optional.  

- When empty or omitted, **no workshop tab** is rendered in the Educates UI.  
- When at least one source is defined, workshop and/or data content is mounted and the tab is enabled.

Supported sources:

- **OCI image** (`spec.files[].image`)  
- **Git repository** (`spec.files[].git`)  
- **HTTP(S) download** (`spec.files[].http`)  

Filters (`includePaths`, `excludePaths`, `newRootPath`, `path`) control what ends up visible.

### vcluster toggle
`spec.vcluster` is a boolean flag.  
- `true` → the datalab provisions a vcluster for runtime isolation.  
- `false` → workloads run directly in the namespace.

### Storage Secret
A Datalab requires credentials to an S3-compatible storage system.  
Credentials are expected to exist in a Kubernetes Secret named via `spec.secretName`, in the same namespace as the Datalab.  

This secret must include at least the `access_key` and `access_secret`. The endpoint and provider are defined in `EnvironmentConfig.data.storage`.

### Identity and Keycloak Resources
Users listed under `spec.users` must already exist in Keycloak.  
When a Datalab is created, the composition also provisions the required **Keycloak resources**:

- A **Group** for the datalab  
- **Group memberships** for the listed users  
- A **Client** and **Role** to protect access to the datalab and installed tooling  

This ensures that authentication and authorization are consistently enforced across the runtime and UI.

---

## Example: Joe (no session by default)

```yaml
# Joe gets a personal datalab s-joe with no pre-created session.
# He must explicitly start a session himself; nothing is running by default.
# No vcluster is provisioned and no workshop files are attached.
# Credentials to storage are expected to exist in a secret "joe" in the same namespace.
# A Keycloak group, role, and client are created; user "joe" must exist in Keycloak.
apiVersion: pkg.internal/v1beta1
kind: Datalab
metadata:
  name: s-joe
spec:
  users:
  - joe
  secretName: joe
```

- Joe’s Datalab exists but is idle until he launches a session.  
- Useful for lightweight, on-demand environments.  
- Keycloak ensures Joe is authorized to access his workspace.  

---

## Example: Jeff and Jim (shared session)

```yaml
# Jeff and Jim share a datalab s-jeff with one default shared session
# automatically created. That session will run permanently until stopped by the operator.
# The lab does not use a vcluster and has no workshop files.
# Credentials to storage are expected to exist in a secret "jeff" in the same namespace.
# A Keycloak group, role, and client are created; users "jeff" and "jim" must exist in Keycloak.
apiVersion: pkg.internal/v1beta1
kind: Datalab
metadata:
  name: s-jeff
spec:
  users:
  - jeff
  - jim
  secretName: jeff
  sessions:
  - default
  vcluster: false
  files: []
```

- A long-running session is started immediately, shared by both users.  
- This is the “always-on” style of datalab.  
- Access is secured through the corresponding Keycloak group and role.  

---

## Example: Jane (with vcluster)

```yaml
# Jane runs a datalab s-jane with a default session automatically created.
# That session will run permanently until stopped by the operator,
# and a dedicated vcluster is provisioned for runtime isolation.
# No workshop files are attached. Credentials to storage are expected
# to exist in a secret "jane" in the same namespace.
# A Keycloak group, role, and client are created; user "jane" must exist in Keycloak.
apiVersion: pkg.internal/v1beta1
kind: Datalab
metadata:
  name: s-jane
spec:
  users:
  - jane
  secretName: jane
  sessions: 
  - default
  vcluster: true
```

- Jane’s workloads run inside an isolated virtual cluster.  
- Ideal for complex labs requiring full Kubernetes privileges.  
- Keycloak resources protect access to Jane’s datalab.  

---

## Example: John (with Git-based workshop files)

```yaml
# John has a datalab s-john with a default session automatically created.
# That session will run permanently until stopped by the operator.
# No vcluster is provisioned. Workshop and data files are pulled from Git,
# enabling the workshop tab in the Educates UI.
# Credentials to storage are expected in a secret "john" in the same namespace.
# A Keycloak group, role, and client are created; user "john" must exist in Keycloak.
apiVersion: pkg.internal/v1beta1
kind: Datalab
metadata:
  name: s-john
spec:
  users:
  - john
  secretName: john
  sessions:
  - default
  vcluster: false
  files:
  - git:
      url: https://github.com/versioneer-tech/datalab-example
      ref: origin/main
    includePaths:
    - /workshop/**
    - /data/**
    - /README.md
    path: .
```

- Preloads workshop materials from Git.  
- Activates the workshop tab in the UI for guided exercises.  
- Keycloak ensures only John has access to this environment and tooling.  

---

## Verifying Provisioning

Once a `Datalab` claim has been applied, you can verify that the provisioning worked.

### Check Composite Status

List all `datalabs` in your namespace:

```bash
kubectl get datalabs -n workspace
```

You should see `READY=True` once reconciliation is complete:

```
NAME       SYNCED   READY   COMPOSITION       AGE
s-joe      True     True    datalab-educates  2m
s-jeff     True     True    datalab-educates  2m
s-jane     True     True    datalab-educates  2m
s-john     True     True    datalab-educates  2m
```

Inspect details:

```bash
kubectl describe datalab s-jeff -n workspace
```

Look for conditions like `Ready=True` and any event messages.

### Find the Storage Secret

Each Datalab references a **Secret in the same namespace** via `spec.secretName`.  
For example, the claim `s-jeff` with `secretName: jeff` requires a Secret named `jeff`.

List Secrets:

```bash
kubectl get secrets -n workspace
```

Inspect:

```bash
kubectl describe secret jeff -n workspace
```

View raw YAML:

```bash
kubectl get secret jeff -n workspace -o yaml
```

Decode keys (AWS style):

```bash
kubectl get secret jeff -n workspace -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' | base64 -d; echo
kubectl get secret jeff -n workspace -o jsonpath='{.data.AWS_SECRET_ACCESS_KEY}' | base64 -d; echo
```

---

## Summary

- A `Datalab` defines users, sessions, optional vcluster, optional workshop files, and integrates with Keycloak.  
- Users must already exist in Keycloak; the Datalab provisions groups, memberships, a client, and a role to secure access.  
- Sessions may be long-lived (auto-created) or on-demand (user started).  
- Each Datalab requires a storage credentials Secret in the same namespace.  
- Workshop files enable the Educates UI workshop tab.  
- Check `kubectl get datalabs` for readiness, ensure Secrets are present, and confirm Keycloak groups/roles are created.  
