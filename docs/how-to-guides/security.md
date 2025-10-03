# Provider Datalab – Security in Cloud Workspaces

Running Datalabs means letting end users run **their own code on your servers**. In practice, this is like operating a shared computer lab: some users are trusted colleagues, others are students, and some may be external partners. Everyone is authenticated, but **authentication is not the same as trust**. An authenticated user can still make mistakes, run unsafe workloads, or attempt to break out of their sandbox. The security model of Datalabs must therefore acknowledge **different trust levels**: users can be trusted to log in, but not necessarily trusted with unrestricted access.

Out of the box, our platform applies a **baseline security model**: workloads are isolated into namespaces, Pods are subject to Kubernetes admission controls, and **NetworkPolicies** block access to sensitive metadata endpoints. This baseline is pragmatic but effective. Beyond it, security can be extended with **Kyverno** policies and other admission controllers to enforce stricter boundaries.

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

## Policy Enforcement

The enforcement of NetworkPolicies depends on the CNI plugin (Cilium, Calico, Antrea, etc.). Without a CNI that supports them, policies have no effect.

We assume:

- **CNI enforces policies** consistently across all nodes.  
- **IMDS endpoints are blocked** via the allow-web-egress policy.  
- **External access** flows through a central ingress controller for TLS, auditing, and routing.  

More restrictive egress controls (e.g., whitelisting PyPI, GitHub, or S3) could be added, but these create significant operational overhead and reduce usability. Our design is intentionally permissive, with the option to tighten later.

Kyverno can be added to enforce stricter pod-level policies across environments. For example, you can block privileged pods, disallow host networking, or restrict image registries. or deploying workloads that would otherwise compromise the host cluster.”

---

## Summary

In our current configuration, the baseline security model is:

- Apply **one permissive egress policy** per environment namespace: allow everything, except block the **cloud metadata endpoint**.  
- Use **PodSecurity Admission** to prevent privilege escalation.  
- Keep policies in the **environment namespace**, where workloads actually run.  
- Route ingress through a central controller for TLS and auditing.  

This setup prioritizes usability for researchers while protecting the cluster’s most critical boundary: preventing pods from stealing cloud instance credentials.  

Over time, this model can evolve into stricter egress filtering or finer-grained ingress/egress rules, but it already provides a safe and pragmatic baseline for multi-tenant Datalabs.
