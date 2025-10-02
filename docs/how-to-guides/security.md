# Security in Datalabs (Cloud Workspaces)

Running Datalabs on Kubernetes requires careful consideration of **network isolation**, **identity and RBAC**, and **multi-tenancy boundaries**. This page outlines the current security model, explains the role of Kubernetes **NetworkPolicies**, and highlights pragmatic decisions made for our IPv4-only cluster.

## Network Isolation with NetworkPolicies

Kubernetes **NetworkPolicies** control how pods can communicate with each other and with external services. By default, a cluster allows all traffic between pods and to the internet. NetworkPolicies reverse this model: once isolation is enabled in a namespace, **only explicitly allowed traffic flows**.  

Policies are **flexible**: they can be as strict as "this pod only talks to another on one port," or as permissive as "all pods in this namespace can reach the internet." What we describe here is not a perfect “zero trust” design but a **pragmatic baseline** that balances usability and protection.

### allow-web-egress

Currently, we deploy a single permissive policy:

- **Pods:** all pods in environment namespaces (where user workloads run)  
- **Allows:** all egress traffic to the internet  
- **Blocks:** access to the **cloud instance metadata endpoint** `169.254.169.254/32`  

This endpoint (known as **IMDS**) provides cloud instance credentials that bypass Kubernetes RBAC if exposed inside a pod. Protecting it is critical in multi-tenant setups.  

📌 **Note:** In our IPv4-only cluster, only `169.254.169.254` must be blocked. In dual-stack or IPv6-only clusters, the corresponding IPv6 endpoint (commonly `fd00:ec2::254`) must also be restricted.

This “allow everything except IMDS” approach gives users the freedom to fetch packages, clone repositories, or access S3 buckets, while removing the most dangerous privilege escalation path.

---

## Why No Policies in Session Namespaces?

NetworkPolicies are namespace-scoped:

- **Egress rules** apply to pods **in the namespace of the policy** (the traffic source).  
- **Ingress rules** apply to pods **in the namespace of the policy** (the traffic destination).  

Since session namespaces in our current design do not host persistent backend pods, applying policies there adds no value. All critical services (such as the `data` service) run in the **environment namespace**, and that is where policies are enforced.

---

## vcluster vs Namespace Security

[vcluster](https://www.vcluster.com/) improves the developer experience by giving each tenant a virtual control plane, but **it does not strengthen security boundaries**:

- All workloads still run in the host namespace.  
- PodSecurity and NetworkPolicies continue to apply at the host namespace level.  
- vcluster does not prevent privileged workloads (`hostPath`, `hostNetwork`, `privileged: true`) unless these are already disallowed by cluster policy.  

**Takeaway:** treat vcluster namespaces the same as direct tenant namespaces. Enable **Pod Security Admission** (`baseline` or `restricted`) and rely on NetworkPolicies to enforce communication boundaries.

---

## CNI and Enforcement

The actual enforcement of NetworkPolicies depends on the CNI plugin (Cilium, Calico, Antrea, etc.). Without a CNI that supports them, policies have no effect.

We assume:

- **CNI enforces policies** consistently across all nodes.  
- **IMDS endpoints are blocked** via the allow-web-egress policy.  
- **External access** flows through a central ingress controller for TLS, auditing, and consistent routing.  

More restrictive egress controls (such as whitelisting PyPI, GitHub, or S3) could be added, but in practice these create significant operational overhead and reduce usability. Our design is deliberately permissive, with the option to tighten later.

---

## Additional Security Layers

- **Namespace isolation:** Each workspace and session runs in its own namespace with scoped RBAC, secrets, and NetworkPolicies.  
- **Ephemeral environments:** Sessions are short-lived and automatically cleaned up, reducing long-term exposure.  
- **Identity integration:** Access is bound to Keycloak groups and roles, enforcing least privilege.  
- **Storage security:** Object storage credentials are provisioned per workspace and scoped to specific buckets.  
- **Baseline protections:** Cluster-wide PodSecurity and NetworkPolicy baselines apply consistently.

---

## Summary

In our current **IPv4-only cluster**, the baseline security model is:

- Apply **one permissive egress policy** per environment namespace: allow everything, except block the **cloud metadata endpoint**.  
- Use **PodSecurity Admission** to prevent privilege escalation.  
- Keep policies in the **environment namespace**, since that is where workloads run.  
- Route ingress through a central controller for consistency and auditing.  

This setup prioritizes usability for researchers while protecting the cluster’s most critical boundary: preventing pods from stealing cloud instance credentials.  

Over time, this model can evolve into stricter egress filtering or finer-grained ingress/egress rules, but it already provides a safe and pragmatic baseline for multi-tenant data labs.  
