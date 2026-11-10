# API Reference

Packages:

- [versioneer.at/v1](#versioneeratv1)

# versioneer.at/v1

Resource Types:

- [Datalab](#datalab)




## Datalab
<sup><sup>[↩ Parent](#versioneeratv1 )</sup></sup>






A Datalab is a tenant-facing, namespaced composite resource. It defines membership, data services, and virtual clusters.

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
      <td>versioneer.at/v1</td>
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
          <br/>
            <i>Validations</i>:<li>!has(self.sessions) || self.sessions.all(s, has(self.vclusters) && s.vcluster in self.vclusters): Each session must select a declared virtual cluster.</li>
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
          PostgreSQL clusters with data storage, optional backup storage, and named databases. The operator creates the databases for the postgres account and adds logins from spec.users. Application setup manages additional ownership and grants.<br/>
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
          Durable workspace PVCs inside named virtual clusters. Workloads use the PVC independently; public session URLs are not provided.<br/>
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
          <br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>vcluster</b></td>
        <td>string</td>
        <td>
          <br/>
          <br/>
            <i>Validations</i>:<li>self == oldSelf: A session cannot move to another virtual cluster.</li>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>namespace</b></td>
        <td>string</td>
        <td>
          <br/>
          <br/>
            <i>Validations</i>:<li>self == oldSelf: A session cannot move to another namespace.</li><li>!self.startsWith("kube-") && self != "agent-sandbox-system": Sessions must use a workload namespace.</li>
            <i>Default</i>: default<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>pvcSize</b></td>
        <td>string</td>
        <td>
          PVC size. Defaults to the platform session size, or 1Gi.<br/>
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
          Additional profiles granted to Datalab users and administrators. Only Datalab administrators receive the built-in cluster-admin profile.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecvclusterskeysecretbindingsindex">secretBindings</a></b></td>
        <td>[]object</td>
        <td>
          Datalab connection Secrets to sync into this virtual cluster.<br/>
          <br/>
            <i>Default</i>: []<br/>
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


### Datalab.spec.vclusters[key].secretBindings[index]
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
          Service instance, primary for storage, or a predefined custom Secret name.<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b><a href="#datalabspecvclusterskeysecretbindingsindextarget">target</a></b></td>
        <td>object</td>
        <td>
          <br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>type</b></td>
        <td>enum</td>
        <td>
          Datalab connection type.<br/>
          <br/>
            <i>Enum</i>: s3, postgres, mongo, redis, registry, custom<br/>
        </td>
        <td>true</td>
      </tr></tbody>
</table>


### Datalab.spec.vclusters[key].secretBindings[index].target
<sup><sup>[↩ Parent](#datalabspecvclusterskeysecretbindingsindex)</sup></sup>





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
          Service and virtual API connection metadata. Managed service and custom connections are ready when their published Secret in the Datalab namespace matches the available source. Readiness does not confirm delivery into a virtual cluster or caller authorization.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabstatusoauth2index">oauth2</a></b></td>
        <td>[]object</td>
        <td>
          OAuth2 discovery by client ID. Contains metadata and Secret references only.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabstatussessionsindex">sessions</a></b></td>
        <td>[]object</td>
        <td>
          Session PVC references inside virtual clusters.<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.status.connections[index]
<sup><sup>[↩ Parent](#datalabstatus)</sup></sup>





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
            <i>Enum</i>: s3, postgres, mongo, redis, registry, custom, vcluster<br/>
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
        <td><b>region</b></td>
        <td>string</td>
        <td>
          S3 region, when configured.<br/>
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


### Datalab.status.oauth2[index]
<sup><sup>[↩ Parent](#datalabstatus)</sup></sup>





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
        <td><b>issuerUrl</b></td>
        <td>string</td>
        <td>
          <br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>name</b></td>
        <td>string</td>
        <td>
          OAuth2 client ID.<br/>
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
        <td><b><a href="#datalabstatusoauth2indexsecretref">secretRef</a></b></td>
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
            <i>Enum</i>: client<br/>
        </td>
        <td>true</td>
      </tr></tbody>
</table>


### Datalab.status.oauth2[index].secretRef
<sup><sup>[↩ Parent](#datalabstatusoauth2index)</sup></sup>





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


### Datalab.status.sessions[index]
<sup><sup>[↩ Parent](#datalabstatus)</sup></sup>





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
      </tr><tr>
        <td><b>pvcName</b></td>
        <td>string</td>
        <td>
          <br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>vcluster</b></td>
        <td>string</td>
        <td>
          <br/>
        </td>
        <td>true</td>
      </tr></tbody>
</table>
