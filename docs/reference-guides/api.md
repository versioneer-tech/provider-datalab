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
        <td><b>environmentName</b></td>
        <td>string</td>
        <td>
          Optional EnvironmentConfig name. Use a lowercase DNS name with 1 to 63 characters. See the installation guide for selection rules.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecstoreskey">stores</a></b></td>
        <td>map[string]object</td>
        <td>
          Managed service instances keyed by name. Names below each instance select PostgreSQL databases, or Valkey key prefixes.<br/>
          <br/>
            <i>Validations</i>:<li>self.all(k, size(k) <= 63 && k.matches('^[a-z]([a-z0-9-]*[a-z0-9])?$')): Instance names must start with a lowercase letter, contain only lowercase letters, digits, or hyphens, end with a letter or digit, and have at most 63 characters.</li>
            <i>Default</i>: map[]<br/>
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
      </tr><tr>
        <td><b><a href="#datalabspecvolumeskey">volumes</a></b></td>
        <td>map[string]object</td>
        <td>
          Named PVCs with optional CSI snapshots in the Datalab host namespace, independent of virtual clusters.<br/>
          <br/>
            <i>Validations</i>:<li>self.all(k, size(k) <= 40 && k.matches("^[a-z]([a-z0-9-]*[a-z0-9])?$")): Volume names must start with a lowercase letter, contain only lowercase letters, digits, or hyphens, end with a letter or digit, and have at most 40 characters.</li>
            <i>Default</i>: map[]<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.stores[key]
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
          Data PVC size as a Kubernetes quantity, such as 1Gi.<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>type</b></td>
        <td>enum</td>
        <td>
          Service type, also used in status.connections.<br/>
          <br/>
            <i>Validations</i>:<li>self == oldSelf: Store type cannot change. Use a new instance name for another service type.</li>
            <i>Enum</i>: postgres, valkey<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>backups</b></td>
        <td>boolean</td>
        <td>
          Enable CSI snapshots. The environment sets the class, schedule, and retention. PostgreSQL pauses the instance; Valkey pauses writes and saves an RDB file. There is no point-in-time recovery.<br/>
          <br/>
            <i>Default</i>: false<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>names</b></td>
        <td>[]string</td>
        <td>
          PostgreSQL database names, or Valkey key prefixes without the final colon. Defaults to one name, default. Names share the instance credentials; Valkey prefixes are not an access boundary.<br/>
          <br/>
            <i>Default</i>: [default]<br/>
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
        <td><b>hibernated</b></td>
        <td>boolean</td>
        <td>
          Stop this instance and its synced Pods. Keep its storage. Set false to resume from the host Datalab.<br/>
          <br/>
            <i>Default</i>: false<br/>
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
      </tr><tr>
        <td><b><a href="#datalabspecvclusterskeyvolumebindingsindex">volumeBindings</a></b></td>
        <td>[]object</td>
        <td>
          Named host volumes to expose as PVCs in this virtual cluster. Requires host mutating admission policies.<br/>
          <br/>
            <i>Default</i>: []<br/>
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
            <i>Enum</i>: s3, postgres, valkey, registry, custom<br/>
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


### Datalab.spec.vclusters[key].volumeBindings[index]
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
          A name declared in spec.volumes.<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b><a href="#datalabspecvclusterskeyvolumebindingsindextarget">target</a></b></td>
        <td>object</td>
        <td>
          <br/>
        </td>
        <td>true</td>
      </tr></tbody>
</table>


### Datalab.spec.vclusters[key].volumeBindings[index].target
<sup><sup>[↩ Parent](#datalabspecvclusterskeyvolumebindingsindex)</sup></sup>





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
          PVC name in the virtual namespace.<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>namespace</b></td>
        <td>string</td>
        <td>
          <br/>
          <br/>
            <i>Validations</i>:<li>!self.startsWith("kube-"): A volume binding must use a workload namespace.</li>
        </td>
        <td>true</td>
      </tr></tbody>
</table>


### Datalab.spec.volumes[key]
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
        <td><b>backups</b></td>
        <td>boolean</td>
        <td>
          Enable scheduled CSI snapshots. The environment sets the class, schedule, and retention.<br/>
          <br/>
            <i>Default</i>: false<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>restoreFrom</b></td>
        <td>string</td>
        <td>
          Existing VolumeSnapshot in the Datalab host namespace to restore into this new volume.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>storage</b></td>
        <td>string</td>
        <td>
          Volume size. Defaults to the platform volume size, or 1Gi.<br/>
        </td>
        <td>false</td>
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
        <td><b><a href="#datalabstatusvclustersindex">vclusters</a></b></td>
        <td>[]object</td>
        <td>
          Instance lifecycle state. Hibernated means the control plane and synced host Pods are gone.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabstatusvolumesindex">volumes</a></b></td>
        <td>[]object</td>
        <td>
          Host PVC state and completed snapshot backups for each named volume.<br/>
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
            <i>Enum</i>: s3, postgres, valkey, registry, custom, vcluster<br/>
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
        <td><b>names</b></td>
        <td>[]string</td>
        <td>
          Logical database names or Valkey key prefixes for a managed store instance.<br/>
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


### Datalab.status.vclusters[index]
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
        <td><b>message</b></td>
        <td>string</td>
        <td>
          <br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>name</b></td>
        <td>string</td>
        <td>
          <br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>phase</b></td>
        <td>enum</td>
        <td>
          <br/>
          <br/>
            <i>Enum</i>: Starting, Running, Hibernating, Hibernated, Resuming, Failed<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>cleanupGeneration</b></td>
        <td>integer</td>
        <td>
          <br/>
          <br/>
            <i>Format</i>: int64<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>cleanupJob</b></td>
        <td>string</td>
        <td>
          <br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>observedGeneration</b></td>
        <td>integer</td>
        <td>
          <br/>
          <br/>
            <i>Format</i>: int64<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.status.volumes[index]
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
        <td><b>phase</b></td>
        <td>enum</td>
        <td>
          <br/>
          <br/>
            <i>Enum</i>: Pending, Bound, Lost<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b><a href="#datalabstatusvolumesindexpvcref">pvcRef</a></b></td>
        <td>object</td>
        <td>
          <br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b><a href="#datalabstatusvolumesindexbackup">backup</a></b></td>
        <td>object</td>
        <td>
          <br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.status.volumes[index].pvcRef
<sup><sup>[↩ Parent](#datalabstatusvolumesindex)</sup></sup>





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


### Datalab.status.volumes[index].backup
<sup><sup>[↩ Parent](#datalabstatusvolumesindex)</sup></sup>





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
        <td><b>readySnapshots</b></td>
        <td>integer</td>
        <td>
          Ready snapshots for the current PVC UID, excluding snapshots being deleted.<br/>
          <br/>
            <i>Minimum</i>: 0<br/>
        </td>
        <td>true</td>
      </tr><tr>
        <td><b>lastSuccessfulTime</b></td>
        <td>string</td>
        <td>
          Creation time of the latest ready snapshot. Absent until a snapshot is ready.<br/>
          <br/>
            <i>Format</i>: date-time<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>
