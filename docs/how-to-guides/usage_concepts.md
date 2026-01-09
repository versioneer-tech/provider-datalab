# Provider Datalab – Usage & Concepts

This section explains how to **use** the `provider-datalab` configuration packages once they are installed. It focuses on the **concepts** of Sessions, Files, vclusters, Storage Secrets, and the required **Keycloak integration** for identity and access.

---

## Concepts

### Sessions
A `Datalab` claim may declare one or more `spec.sessions`.  

- If at least one session is listed, a corresponding **WorkshopSession** is automatically created and will run permanently until stopped by the operator.  
- If no sessions are given, no runtime will be started; users must explicitly launch a session themselves (`auto` mode).  

Sessions can also be patched into the spec later if needed.

### Persistence

Each `Datalab` session is equipped with a **persistent volume** for storing files, in addition to the connected object storage.  This ensures that user data and session state are preserved even if the workshop pod is restarted or rescheduled by Kubernetes.  Installing code libraries, handling metadata, or working with Git repositories often generates many small files that may be updated frequently. A storage class providing **NFS-like capabilities** is usually a good fit for these kinds of workloads, **object storage** abstractions are not.

The **persistent volume claim (PVC)** is **tied to the active session** and will be deleted automatically when the workshop session shuts down (for example, through a culling process when using session mode `auto`). This does **not necessarily mean that data is lost** — when the session is restarted from the same manifests, Kubernetes will recreate the PVC with the same name, reattaching it to the existing data in environments that use an **NFS server** or another **shared storage backend**, since the PVC will point to the **same physical folder**.

This behavior works as long as the associated `StorageClass` has its `reclaimPolicy` set to `Retain` (not `Delete`), ensuring that data is not removed externally. It also depends on maintaining a **consistent link between the PVC name and the actual storage path**.  If the underlying storage system assigns **randomized volume identifiers** (such as UIDs for folder paths), the data will still remain on the storage backend after the session ends, but Kubernetes will not automatically reattach it to a new PVC — manual reassociation may then be required.

### Authentication

Access to a `Datalab` session is restricted, with the environment configuration determining the authentication strategy. By default, the same credentials used to access the connected object storage buckets are also applied for session login. Authentication can be globally disabled by setting `auth.type = none`, for example, in air-gapped environments or when access is already secured at the ingress level through other mechanisms.  

Each `Datalab` automatically provisions a dedicated Keycloak **OAuth2 client**, which can be used to protect the session using standard **OIDC** flows.  
Full integration and automated configuration of this setup are planned for future releases.


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

### Security and Access Policy
The `spec.security` section controls access permissions and runtime privilege level for sessions.

Key fields:

- `policy` — defines Pod Security Standard (`restricted`, `baseline`, `privileged`).  
  - `privileged` enables Docker-in-Docker with 20 Gi of local storage.  
- `kubernetesAccess` — whether a Kubernetes service account token is mounted inside the session.  
- `kubernetesRole` — defines in-namespace RBAC level (`admin`, `edit`, `view`).  

### Resource Quotas
The `spec.quota` section allows per-Datalab overrides of default compute and storage budgets.  

- `memory` — memory allocation per session (default 2 Gi).  
- `storage` — persistent volume size (default 1 Gi).  
- `budget` — Educates resource budget profile (`small`, `medium`, `large`, `x-large`, etc.).  

When unspecified, defaults from the EnvironmentConfig apply.

| Budget    | CPU   | Memory |
|-----------|-------|--------|
| small     | 1000m | 1Gi    |
| medium    | 2000m | 2Gi    |
| large     | 4000m | 4Gi    |
| x-large   | 8000m | 8Gi    |
| xx-large  | 8000m | 12Gi   |
| xxx-large | 8000m | 16Gi   |

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

## Example: Jeff and Jim (shared session, privileged with Docker)

```yaml
# Jeff and Jim share a datalab s-jeff with one default shared session
# automatically created. That session will run permanently until stopped by the operator.
# The lab does not use a vcluster and has no workshop files.
# Credentials to storage are expected to exist in a secret "jeff" in the same namespace.
# A Keycloak group, role, and client are created; users "jeff" and "jim" must exist in Keycloak.
# This configuration runs the lab in privileged mode:
# - Security policy: "privileged" → automatically enables Docker with 20 Gi workspace storage.
# - Session quota: increased to 6 Gi memory, 60 Gi storage, budget class "x-large".
# - Kubernetes API access is disabled (kubernetesAccess=false).
# Additionally, two PostgreSQL databases are provisioned for the lab: "dev" and "prod".
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
  quota:
    memory: 6Gi
    storage: 60Gi
    budget: x-large
  files: []
  security:
    policy: privileged
    kubernetesAccess: false
  databases:
    host0:
      names:
      - dev
      - prod
      storage: 10Gi
```

- A long-running session is started immediately, shared by both users.  
- Runs in **privileged mode** with **Docker support** and increased ephemeral disk (20 Gi).  
- **No Kubernetes API access** is granted inside the environment.  
- Access is secured through the corresponding Keycloak group and role.

---

## Example: Jane (isolated vcluster with admin role and higher quota)

```yaml
# Jane runs a datalab s-jane with a default session automatically created.
# That session will run permanently until stopped by the operator,
# and a dedicated vcluster is provisioned for runtime isolation.
# No workshop files are attached. Credentials to storage are expected
# to exist in a secret "jane" in the same namespace.
# A Keycloak group, role, and client are created; user "jane" must exist in Keycloak.
# This configuration explicitly overrides default resource quotas and security settings:
# - Session quota: increased to 4 Gi memory, 10 Gi storage, budget class "x-large".
# - Kubernetes role: elevated to "admin" for full namespace permissions.
# Additionally, one PostgreSQL database is provisioned for the lab: "analytics".
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
  quota:
    memory: 4Gi
    storage: 10Gi
    budget: x-large
  security:
    kubernetesRole: admin
  databases:
    host0:
      names:
      - analytics
      storage: 3Gi
```

- Jane’s workloads run inside an **isolated virtual cluster** (`vcluster: true`).  
- The **admin role** grants full control within her namespace/vcluster.  
- Increased quota provides additional compute and storage capacity.  
- Suitable for advanced development or testing requiring full Kubernetes control.  
- Keycloak enforces role-based access protection for this lab.  

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

```bash
kubectl get datalabs -n workspace
```

You should see all Datalabs `READY=True` once reconciliation is complete:

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

```bash
kubectl get secret jeff -n workspace -o yaml
```

Decode credentials (AWS-style):

```bash
kubectl get secret jeff -n workspace -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' | base64 -d; echo
kubectl get secret jeff -n workspace -o jsonpath='{.data.AWS_SECRET_ACCESS_KEY}' | base64 -d; echo
```

### Connect to Databases

Starting with version 0.3.0, databases can be provisioned on a dedicated PostgreSQL host. Optionally, these databases can also be exposed externally using a `TLSRoute`, enabling secure access from outside the cluster.

A dedicated `admin` database user is created automatically and is set as the owner of all provisioned databases. This user has full administrative privileges, including the ability to create extensions, manage schemas, and grant permissions to other users.

All additional users are created as regular database roles. Access to the databases can be granted by the administrator as required, depending on the desired access model.

Database credentials are managed by the PostgreSQL operator and stored as Kubernetes Secrets. To locate the credentials for the administrative user, look for Secrets with the suffix `*-pguser-admin`. These Secrets contain the connection details needed to authenticate as the database administrator.

---

## Summary

- A `Datalab` defines users, sessions, optional vcluster, quotas, and security policies.  
- Security controls combine **Pod Security Standards**, **Kubernetes roles**, and **Docker privilege** toggles.  
- Each Datalab requires a storage credential Secret.  
- Users must already exist in Keycloak; the Datalab provisions groups, memberships, a client, and a role.  
- Sessions may be long-lived (auto-created) or on-demand (user started).  
- Workshop files enable the Educates UI workshop tab.  
- Check `kubectl get datalabs` for readiness and confirm Secret and Keycloak resource creation.  
