# API Reference

Packages:

- [pkg.internal/v1beta2](#pkginternalv1beta2)

# pkg.internal/v1beta2

Resource Types:

- [Datalab](#datalab)




## Datalab
<sup><sup>[↩ Parent](#pkginternalv1beta2 )</sup></sup>






A Datalab is a tenant-facing, namespaced composite resource. It defines membership, sessions, and data services.

<table>
    <thead>
        <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Description</th>
            <th>Required</th>
        </tr>
    </thead>
    <tbody><tr>
      <td><b>apiVersion</b></td>
      <td>string</td>
      <td>pkg.internal/v1beta2</td>
      <td>true</td>
      </tr>
      <tr>
      <td><b>kind</b></td>
      <td>string</td>
      <td>Datalab</td>
      <td>true</td>
      </tr>
      <tr>
      <td><b><a href="https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.27/#objectmeta-v1-meta">metadata</a></b></td>
      <td>object</td>
      <td>Refer to the Kubernetes API documentation for the fields of the `metadata` field.</td>
      <td>true</td>
      </tr><tr>
        <td><b><a href="#datalabspec">spec</a></b></td>
        <td>object</td>
        <td>
          Desired configuration of the datalab.<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b><a href="#datalabstatus">status</a></b></td>
        <td>object</td>
        <td>
          Current observed state of the datalab.<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec
<sup><sup>[↩ Parent](#datalab)</sup></sup>



Desired configuration of the datalab.

<table>
    <thead>
        <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Description</th>
            <th>Required</th>
        </tr>
    </thead>
    <tbody><tr>
        <td><b>users</b></td>
        <td>[]string</td>
        <td>
          Users associated with this datalab.<br/>
          <br/>
            <i>Default</i>: []<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b><a href="#datalabspeccachestoreskey">cacheStores</a></b></td>
        <td>map[string]object</td>
        <td>
          Optional cache stores for this datalab, implemented via Redis and managed through the Redis Kubernetes operator.<br/>
          <br/>
            <i>Validations</i>:<li>self.all(k, size(k) <= 63 && k.matches('^[a-z]([a-z0-9-]*[a-z0-9])?$')): Instance names must start with a lowercase letter, contain only lowercase letters, digits, or hyphens, end with a letter or digit, and have at most 63 characters.</li>
            <i>Default</i>: map[]<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecdatabaseskey">databases</a></b></td>
        <td>map[string]object</td>
        <td>
          Optional PostgreSQL hosts (PostgresCluster instances) to provision for this datalab. Each host defines a data volume size and an optional pgBackRest repository size, plus a list of logical PostgreSQL databases to create inside that cluster. Ownership and privileges are derived from spec.users by the Composition.<br/>
          <br/>
            <i>Validations</i>:<li>self.all(k, size(k) <= 63 && k.matches('^[a-z]([a-z0-9-]*[a-z0-9])?$')): Instance names must start with a lowercase letter, contain only lowercase letters, digits, or hyphens, end with a letter or digit, and have at most 63 characters.</li>
            <i>Default</i>: map[]<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecdocumentstoreskey">documentStores</a></b></td>
        <td>map[string]object</td>
        <td>
          Optional document stores for this datalab, implemented via MongoDB and managed through the MongoDB Kubernetes operator.<br/>
          <br/>
            <i>Validations</i>:<li>self.all(k, size(k) <= 63 && k.matches('^[a-z]([a-z0-9-]*[a-z0-9])?$')): Instance names must start with a lowercase letter, contain only lowercase letters, digits, or hyphens, end with a letter or digit, and have at most 63 characters.</li>
            <i>Default</i>: map[]<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecsessionsindex">sessions</a></b></td>
        <td>[]object</td>
        <td>
          Sessions declared for this datalab.<br/>
          <br/>
            <i>Default</i>: []<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecuseroverrideskey">userOverrides</a></b></td>
        <td>map[string]object</td>
        <td>
          Optional per-user override configuration.
<br/>
          <br/>
            <i>Default</i>: map[]<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecvclusterskey">vclusters</a></b></td>
        <td>map[string]object</td>
        <td>
          <br/>
          <br/>
            <i>Validations</i>:<li>self.all(k, size(k) <= 63 && k.matches('^[a-z]([a-z0-9-]*[a-z0-9])?$')): Instance names must start with a lowercase letter, contain only lowercase letters, digits, or hyphens, end with a letter or digit, and have at most 63 characters.</li>
            <i>Default</i>: map[]<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.cacheStores[key]
<sup><sup>[↩ Parent](#datalabspec)</sup></sup>





<table>
    <thead>
        <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Description</th>
            <th>Required</th>
        </tr>
    </thead>
    <tbody><tr>
        <td><b>storage</b></td>
        <td>string</td>
        <td>
          Storage size for Redis persistent data volume as a Kubernetes quantity (e.g., "1Gi", "10Gi"). Effective default: "1Gi".<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>type</b></td>
        <td>enum</td>
        <td>
          Service type.<br/>
          <br/>
            <i>Enum</i>: redis<br/>
            <i>Default</i>: redis<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>backupStorage</b></td>
        <td>string</td>
        <td>
          Storage size for the Redis backup PVC as a Kubernetes quantity. A positive value enables daily full RDB snapshots. Zero or an omitted value disables backups.<br/>
          <br/>
            <i>Default</i>: 0<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.databases[key]
<sup><sup>[↩ Parent](#datalabspec)</sup></sup>





<table>
    <thead>
        <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Description</th>
            <th>Required</th>
        </tr>
    </thead>
    <tbody><tr>
        <td><b>names</b></td>
        <td>[]string</td>
        <td>
          Logical PostgreSQL database names to create within this host (e.g., "prod", "dev").<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>storage</b></td>
        <td>string</td>
        <td>
          Storage size for the PostgreSQL data PVC of this PostgresCluster as a Kubernetes quantity (e.g., "1Gi", "10Gi").<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>type</b></td>
        <td>enum</td>
        <td>
          Service type.<br/>
          <br/>
            <i>Enum</i>: postgres<br/>
            <i>Default</i>: postgres<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>backupStorage</b></td>
        <td>string</td>
        <td>
          Storage size for the pgBackRest repository PVC (backup volume, including WAL archive) as a Kubernetes quantity (e.g., "10Gi", "100Gi"). Zero or an omitted value disables backups.<br/>
          <br/>
            <i>Default</i>: 0<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.documentStores[key]
<sup><sup>[↩ Parent](#datalabspec)</sup></sup>





<table>
    <thead>
        <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Description</th>
            <th>Required</th>
        </tr>
    </thead>
    <tbody><tr>
        <td><b>storage</b></td>
        <td>string</td>
        <td>
          Storage size for MongoDB persistent data volume as a Kubernetes quantity (e.g., "5Gi", "20Gi"). Effective default: "10Gi".<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>type</b></td>
        <td>enum</td>
        <td>
          Service type.<br/>
          <br/>
            <i>Enum</i>: mongo<br/>
            <i>Default</i>: mongo<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>backupStorage</b></td>
        <td>string</td>
        <td>
          Storage size for the MongoDB backup PVC as a Kubernetes quantity. A positive value enables daily full backups with mongodump and the oplog. Zero or an omitted value disables backups.<br/>
          <br/>
            <i>Default</i>: 0<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.sessions[index]
<sup><sup>[↩ Parent](#datalabspec)</sup></sup>





<table>
    <thead>
        <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Description</th>
            <th>Required</th>
        </tr>
    </thead>
    <tbody><tr>
        <td><b>name</b></td>
        <td>string</td>
        <td>
          Session name.<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>state</b></td>
        <td>enum</td>
        <td>
          Desired runtime lifecycle for this session. Started sessions create an active runtime session. Stopped sessions keep their Datalab-owned workspace PVC but do not create a runtime.
<br/>
          <br/>
            <i>Enum</i>: started, stopped<br/>
            <i>Default</i>: started<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.userOverrides[key]
<sup><sup>[↩ Parent](#datalabspec)</sup></sup>





<table>
    <thead>
        <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Description</th>
            <th>Required</th>
        </tr>
    </thead>
    <tbody><tr>
        <td><b>grantedAt</b></td>
        <td>string</td>
        <td>
          RFC3339 timestamp indicating when the role became active.
<br/>
          <br/>
            <i>Format</i>: date-time<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>role</b></td>
        <td>enum</td>
        <td>
          Assigned role for the user.<br/>
          <br/>
            <i>Enum</i>: admin, user<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.vclusters[key]
<sup><sup>[↩ Parent](#datalabspec)</sup></sup>



Virtual Kubernetes clusters keyed by instance name.

<table>
    <thead>
        <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Description</th>
            <th>Required</th>
        </tr>
    </thead>
    <tbody><tr>
        <td><b><a href="#datalabspecvclusterskeygroupsindex">groups</a></b></td>
        <td>[]object</td>
        <td>
          Additional access profiles. All Datalab users receive the built-in cluster-admin profile.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>secretBindings</b></td>
        <td>[]object</td>
        <td>
          Datalab connection Secrets to sync into this virtual cluster. Each binding requires
          <code>type</code>, <code>name</code>, and <code>target</code>, with a target <code>namespace</code>
          and <code>name</code>. Types include <code>custom</code> for predefined Secrets.
          Only ready connections generate mappings. Data keys do not change. See
          <a href="../how-to-guides/vcluster.md#secret-bindings">Secret bindings</a>.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>storage</b></td>
        <td>string</td>
        <td>
          Control-plane PVC size. The environment default is used when omitted.<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.vclusters[key].groups[index]
<sup><sup>[↩ Parent](#datalabspecvclusterskey)</sup></sup>





<table>
    <thead>
        <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Description</th>
            <th>Required</th>
        </tr>
    </thead>
    <tbody><tr>
        <td><b>name</b></td>
        <td>string</td>
        <td>
          Profile name used for its Keycloak role and connection set.<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>namespace</b></td>
        <td>string</td>
        <td>
          Virtual namespace to create, or '*' for virtual cluster administration.<br/>
          <br/>
            <i>Validations</i>:<li>self != "default" && !self.startsWith("kube-"): Select a workload namespace, not a Kubernetes system namespace.</li>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>role</b></td>
        <td>enum</td>
        <td>
          Kubernetes ClusterRole granted to this profile.<br/>
          <br/>
            <i>Enum</i>: view, edit, admin, cluster-admin<br/>
        </td>
        <td>true</td>
      </tr></tbody>
</table>


### Datalab.status
<sup><sup>[↩ Parent](#datalab)</sup></sup>



Current observed state of the datalab.

<table>
    <thead>
        <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Description</th>
            <th>Required</th>
        </tr>
    </thead>
    <tbody><tr>
        <td><b><a href="#datalabstatusconnectionsindex">connections</a></b></td>
        <td>[]object</td>
        <td>
          Service and virtual API connection metadata. Service readiness reports source observation, not Secret delivery.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabstatussessionskey">sessions</a></b></td>
        <td>map[string]object</td>
        <td>
          Map of session IDs and their lifecycle state and runtime details.<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.status.connections[index]
<sup><sup>[↩ Parent](#datalabstatus)</sup></sup>

Service connections use the same `type` and `name` pair as a Secret binding.
`secretRef` identifies the host source. Custom connections are listed only
when available. Source readiness does not report virtual Secret delivery.
Datalab readiness requires every published connection and the existing
resource checks to be ready.




<table>
    <thead>
        <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Description</th>
            <th>Required</th>
        </tr>
    </thead>
    <tbody><tr>
        <td><b>name</b></td>
        <td>string</td>
        <td>
          <br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>ready</b></td>
        <td>boolean</td>
        <td>
          <br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b><a href="#datalabstatusconnectionsindexsecretref">secretRef</a></b></td>
        <td>object</td>
        <td>
          <br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>type</b></td>
        <td>enum</td>
        <td>
          <br/>
          <br/>
            <i>Enum</i>: s3, postgres, mongo, redis, vcluster<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>endpoint</b></td>
        <td>string</td>
        <td>
          <br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>group</b></td>
        <td>string</td>
        <td>
          <br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>instance</b></td>
        <td>string</td>
        <td>
          <br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>role</b></td>
        <td>string</td>
        <td>
          <br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>targetNamespace</b></td>
        <td>string</td>
        <td>
          <br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.status.connections[index].secretRef
<sup><sup>[↩ Parent](#datalabstatusconnectionsindex)</sup></sup>





<table>
    <thead>
        <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Description</th>
            <th>Required</th>
        </tr>
    </thead>
    <tbody><tr>
        <td><b>name</b></td>
        <td>string</td>
        <td>
          <br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>namespace</b></td>
        <td>string</td>
        <td>
          <br/>
        </td>
        <td>true</td>
      </tr></tbody>
</table>


### Datalab.status.sessions[key]
<sup><sup>[↩ Parent](#datalabstatus)</sup></sup>



Observed state of a single datalab session.

<table>
    <thead>
        <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Description</th>
            <th>Required</th>
        </tr>
    </thead>
    <tbody><tr>
        <td><b>message</b></td>
        <td>string</td>
        <td>
          Latest observed status message for the session runtime.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>phase</b></td>
        <td>string</td>
        <td>
          Latest observed lifecycle phase for the session runtime.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>state</b></td>
        <td>enum</td>
        <td>
          Desired lifecycle state for the declared session.<br/>
          <br/>
            <i>Enum</i>: started, stopped<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>url</b></td>
        <td>string</td>
        <td>
          Public URL of the active session.<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>
