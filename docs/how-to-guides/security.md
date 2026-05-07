# Provider Datalab – Security in Cloud Workspaces

Running Datalabs means letting end users run **their own code on your servers**. In practice, this is like operating a shared computer lab: some users are trusted colleagues, others are students, and some may be external partners. Everyone is authenticated, but **authentication is not the same as trust**. An authenticated user can still make mistakes, run unsafe workloads, or attempt to break out of their sandbox. The security model of Datalabs must therefore acknowledge **different trust levels**: users can be trusted to log in, but not necessarily trusted with unrestricted access.

Out of the box, our platform applies a **baseline security model**: workloads are isolated into namespaces, Pods are subject to Kubernetes admission controls, and **NetworkPolicies** block access to sensitive metadata endpoints. This baseline is pragmatic but effective. Beyond it, security can be extended with **Kyverno** policies and other admission controllers to enforce stricter boundaries.

---

## Datalabs as Sandboxes for Agents

A Datalab session is a sandbox for both humans and agents, but the practical question is what that sandbox is authorized to touch:

- With `vcluster: false`, workloads are sandboxed to the Datalab's dedicated host-cluster namespace.
- With `vcluster: true`, users and agents also get a dedicated virtual Kubernetes API. Workloads still run under the host namespace's Pod Security, NetworkPolicy, quota, and admission controls.
- `kubernetesAccess` exposes a Kubernetes API token inside the session. The token is scoped to the configured namespace or vcluster and its role is controlled by `kubernetesRole`.
- Storage and service credentials are intentionally exposed to the session when configured. A user or agent can modify any state those credentials allow, such as workspace files, object-storage contents, registry images, or data in attached services.

This means agents should be treated like authorized users with automation speed. They cannot do more than the session's credentials, RBAC, and policies allow, but they can accidentally or intentionally change everything inside that allowed scope. Durable guardrails therefore belong outside the session: database backups, bucket versioning, retention policy, admission control, quotas, audit logs, and lifecycle management. The goal is defense in depth through platform policy, not trust in the agent process.

### Example Security Audit

| Example | Runtime boundary | Kubernetes access | Risk level | Notes for agent workloads |
| --- | --- | --- | --- | --- |
| `s-jeff` (`002-lab.yaml`) | No active session by default; managed services are created in the dedicated runtime namespace | Disabled (`kubernetesAccess: false`) | Lowest | Good default for service validation and idle environments. The example has no running session and no session token. |
| `s-joe` (`001-lab.yaml`) | No active session by default; a later session would run in a dedicated host namespace | Default token with `edit` role if a session is started | Low while idle, medium when started | Safe as an idle personal Datalab. For agents, consider `kubernetesAccess: false` unless Kubernetes API access is required. |
| `s-john` (`004-lab.yaml`) | Active sessions in a dedicated host namespace (`vcluster: false`) | Token enabled with `edit` role | Medium | This is still sandboxed by namespace, Pod Security, NetworkPolicy, and quota. Agents can create real host-cluster namespaced resources and can write to exposed workspace and storage state. |
| `s-jane` (`003-lab.yaml`) | Active session with a dedicated vcluster (`vcluster: true`) | Token enabled with `admin` role in the vcluster | Highest | Best fit for trusted build-heavy workflows. `privileged` mode, Docker, registry, and vcluster admin access make it powerful; use only where that level of trust is intended. |

For a conservative agent profile, start with `vcluster: true`, `policy: baseline` or `restricted`, `kubernetesRole: edit`, and only expose storage or service credentials that the agent is meant to mutate. Enable `privileged` mode and Docker only for trusted workloads that need them.

---

## Configurable Security Options

Datalabs expose configurable runtime security through the `spec.security` section of the `Datalab` resource. This allows operators to adjust the trust level per environment:

- **`policy`** defines the Pod Security Standard (`restricted`, `baseline`, `privileged`).  
  - `restricted` → strictest: disallows most privileges.  
  - `baseline` → safe default: blocks host access and elevated privileges.  
  - `privileged` → relaxed: allows Docker-in-Docker with 20 Gi of local storage.  
- **`kubernetesAccess`** toggles whether a Kubernetes API token is mounted in the session pod. When disabled, users can run workloads but not interact with the cluster API.  
- **`kubernetesRole`** sets the RBAC level (`view`, `edit`, `admin`) within the Datalab namespace or vcluster.

---

## Network Isolation with NetworkPolicies

Kubernetes **NetworkPolicies** control how pods communicate with each other and with external services. By default, a cluster allows all pod-to-pod and internet traffic. NetworkPolicies reverse this: once isolation is enabled, **only explicitly allowed traffic flows**.

Policies are **flexible**: they can be as strict as “this pod only talks to another on one port,” or as permissive as “all pods in this namespace can reach the internet.” What we apply here is not a perfect “zero trust” design but a **pragmatic baseline** balancing usability and protection.

When a Datalab is created, **NetworkPolicies are provisioned automatically** in the corresponding namespace:

- **Egress rules** apply to pods in the namespace (the traffic source).  
- **Ingress rules** apply to pods in the namespace (the traffic destination).  

### allow-web-egress

Currently, we deploy a single permissive policy:

- **Pods:** all pods in environment namespaces (where user workloads run)  
- **Allows:** all egress traffic to the internet  
- **Blocks:** access to the **cloud instance metadata endpoint** `169.254.169.254/32`  

This endpoint (known as **IMDS**) provides cloud instance credentials that bypass Kubernetes RBAC if exposed inside a pod. Protecting it is critical in multi-tenant setups.  

**Note:** In our IPv4-only cluster, only `169.254.169.254` must be blocked. In dual-stack or IPv6-only clusters, the corresponding IPv6 endpoint (commonly `fd00:ec2::254`) must also be restricted.

This “allow everything except IMDS” approach ensures users can fetch packages, clone repositories, or access S3 buckets, while removing the most dangerous privilege escalation path.

---

## vcluster vs Namespace Security

[vcluster](https://www.vcluster.com/) improves the developer experience by giving each tenant a virtual control plane, but **it does not create stronger isolation**:

- All workloads still run in the host namespace.  
- PodSecurity and NetworkPolicies apply at the host namespace level.  
- vcluster **mirrors host cluster policies**: it does not itself prevent privileged workloads (`hostPath`, `hostNetwork`, `privileged: true`) unless these are already disallowed at cluster level.  

**Takeaway:** treat vcluster namespaces the same as direct tenant namespaces. Enable **Pod Security Admission** (`baseline` or `restricted`) and rely on NetworkPolicies for communication boundaries.

---

## DNS Architecture in Workshop Environments

For workshop-style environments that spin up many short-lived vclusters, starting a full DNS service inside every vcluster would slow down startup and waste resources. Instead, a **shared DNS service in the host cluster** handles name resolution for all vclusters.

When a vcluster is created, a small **CoreDNS Service and Deployment** is automatically deployed in the host cluster (for example `kube-dns-x-kube-system-x-my-vcluster`).  
Pods inside the vcluster still use normal Kubernetes DNS names like `kube-dns.kube-system.svc.cluster.local`, but those lookups are transparently routed to the host-level DNS service.  
That host DNS server then talks to the vcluster’s API to resolve internal service names.

**Advantages:**
- Fast startup — no DNS bootstrap delay per vcluster  
- Lower resource use — one lightweight host DNS handles many environments  
- Simpler networking — all workloads share the same cluster network  
- Central visibility — DNS logging and policies stay managed in one place  

From the user’s point of view, everything behaves as expected: pods inside each workshop can resolve service names normally, without needing to know that DNS is handled outside their vcluster. However, some cloud environments differ in how their CNI plugins route service traffic, which can affect how the host DNS reaches the vcluster API. In such cases, minor adjustments to NetworkPolicies or CoreDNS endpoints may be required to restore internal name resolution.

---

## Policy Enforcement

The enforcement of NetworkPolicies depends on the CNI plugin (Cilium, Calico, Antrea, etc.). Without a CNI that supports them, policies have no effect.

We assume:

- **CNI enforces policies** consistently across all nodes.  
- **IMDS endpoints are blocked** via the allow-web-egress policy.  
- **External access** flows through a central ingress controller for TLS, auditing, and routing.  

More restrictive egress controls (e.g., whitelisting PyPI, GitHub, or S3) could be added, but these create significant operational overhead and reduce usability. Our design is intentionally permissive, with the option to tighten later.

Kyverno can be added to enforce stricter pod-level policies across environments. For example, you can block privileged pods, disallow host networking, or restrict image registries — preventing workloads that could otherwise compromise the host cluster.

---

## Summary

In our current configuration, the baseline security model is:

- Apply **one permissive egress policy** per environment namespace: allow everything, except block the **cloud metadata endpoint**.  
- Use **PodSecurity Admission** to prevent privilege escalation.  
- Expose **security knobs** per Datalab:  
  - Enable or disable Kubernetes API access (`kubernetesAccess`).  
  - Configure role-based privileges (`kubernetesRole`).  
  - Select an overall Pod Security profile (`restricted`, `baseline`, `privileged`).  
- Keep policies in the **environment namespace**, where workloads actually run.  
- Route ingress through a central controller for TLS and auditing.  

This setup prioritizes usability for researchers while protecting the cluster’s most critical boundary: preventing pods from stealing cloud instance credentials.  

Over time, this model can evolve into stricter egress filtering or finer-grained ingress/egress rules, but it already provides a safe and pragmatic baseline for multi-tenant Datalabs.
