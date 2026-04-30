# API Reference

Packages:

- [pkg.internal/v1beta1](#pkginternalv1beta1)

# pkg.internal/v1beta1

Resource Types:

- [Datalab](#datalab)




## Datalab
<sup><sup>[↩ Parent](#pkginternalv1beta1 )</sup></sup>






A Datalab is a tenant-facing, namespaced composite resource. It defines ownership, membership, and optional file bundles to materialize in the environment.

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
      <td>pkg.internal/v1beta1</td>
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
            <i>Default</i>: map[]<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecdata">data</a></b></td>
        <td>object</td>
        <td>
          Optional settings for the Data component. When enabled, the composition provisions the data service UI and mounts workspace storage into it at /data.<br/>
          <br/>
            <i>Default</i>: map[]<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecdatabaseskey">databases</a></b></td>
        <td>map[string]object</td>
        <td>
          Optional PostgreSQL hosts (PostgresCluster instances) to provision for this datalab. Each host defines a data volume size and a pgBackRest repository size, plus a list of logical PostgreSQL databases to create inside that cluster. Ownership and privileges are derived from spec.users by the Composition.<br/>
          <br/>
            <i>Default</i>: map[]<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecdocumentstoreskey">documentStores</a></b></td>
        <td>map[string]object</td>
        <td>
          Optional document stores for this datalab, implemented via MongoDB and managed through the MongoDB Kubernetes operator.<br/>
          <br/>
            <i>Default</i>: map[]<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecfilesindex">files</a></b></td>
        <td>[]object</td>
        <td>
          File bundles to fetch from remote sources and copy into the environment. Supports image, git, and http sources, path filtering, and optional credentials.<br/>
          <br/>
            <i>Default</i>: []<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecquota">quota</a></b></td>
        <td>object</td>
        <td>
          Optional per-datalab session quota overrides. If a field is not specified here, the composition falls back to EnvironmentConfig at `spec.defaults.quota`, and then to hard defaults. Effective defaults (when neither XR nor EnvironmentConfig provides a value): memory=2Gi, storage=1Gi, budget=medium.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecregistry">registry</a></b></td>
        <td>object</td>
        <td>
          Optional settings for the in-session Docker registry. When enabled, a registry service is added to the session applications.<br/>
          <br/>
            <i>Default</i>: map[]<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>secretName</b></td>
        <td>string</td>
        <td>
          Name of the Secret containing the credentials to access the storage associated with this Datalab. The Secret must exist in the same namespace as the Datalab.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecsecurity">security</a></b></td>
        <td>object</td>
        <td>
          Optional per-datalab session security settings. If a field is not specified here, the composition falls back to EnvironmentConfig at `spec.defaults.security`, and then to hard defaults. Effective defaults (when neither XR nor EnvironmentConfig provides a value): policy=baseline, kubernetesAccess=true, kubernetesRole=edit. When policy is "privileged", Docker is automatically enabled with 20Gi storage.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>sessions</b></td>
        <td>[]string</td>
        <td>
          Sessions to be started for this datalab.<br/>
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
        <td><b>vcluster</b></td>
        <td>boolean</td>
        <td>
          Whether to provision an isolated vcluster for each datalab session.<br/>
          <br/>
            <i>Default</i>: false<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecvectorstoreskey">vectorStores</a></b></td>
        <td>map[string]object</td>
        <td>
          Optional vector stores for this datalab, implemented via Qdrant and managed through the Qdrant Kubernetes operator.<br/>
          <br/>
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
      </tr></tbody>
</table>


### Datalab.spec.data
<sup><sup>[↩ Parent](#datalabspec)</sup></sup>



Optional settings for the Data component. When enabled, the composition provisions the data service UI and mounts workspace storage into it at /data.

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
        <td><b>enabled</b></td>
        <td>boolean</td>
        <td>
          Whether to provision the Data component for this Datalab session. Effective default: true.<br/>
          <br/>
            <i>Default</i>: true<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>readOnlyMount</b></td>
        <td>boolean</td>
        <td>
          Whether the workspace storage should be mounted read-only in the Data component. Effective default: false.<br/>
          <br/>
            <i>Default</i>: false<br/>
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
        <td><b>backupStorage</b></td>
        <td>string</td>
        <td>
          Storage size for the pgBackRest repository PVC (backup volume, including WAL archive) as a Kubernetes quantity (e.g., "10Gi", "100Gi").<br/>
        </td>
        <td>true</td>
      </tr><tr>
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
      </tr></tbody>
</table>


### Datalab.spec.files[index]
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
        <td><b>excludePaths</b></td>
        <td>[]string</td>
        <td>
          Glob patterns to exclude from the source.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecfilesindexgit">git</a></b></td>
        <td>object</td>
        <td>
          Git repository source configuration.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecfilesindexhttp">http</a></b></td>
        <td>object</td>
        <td>
          HTTP source configuration for downloading an asset or archive.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecfilesindeximage">image</a></b></td>
        <td>object</td>
        <td>
          Container image source configuration.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>includePaths</b></td>
        <td>[]string</td>
        <td>
          Glob patterns to include from the source.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>newRootPath</b></td>
        <td>string</td>
        <td>
          Subdirectory within the source to treat as the root.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>path</b></td>
        <td>string</td>
        <td>
          Destination directory for extracted files.<br/>
          <br/>
            <i>Default</i>: .<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.files[index].git
<sup><sup>[↩ Parent](#datalabspecfilesindex)</sup></sup>



Git repository source configuration.

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
        <td><b>lfsSkipSmudge</b></td>
        <td>boolean</td>
        <td>
          If true, do not fetch Git LFS objects.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>ref</b></td>
        <td>string</td>
        <td>
          Branch, tag, or commit to fetch.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecfilesindexgitrefselection">refSelection</a></b></td>
        <td>object</td>
        <td>
          Resolve an explicit ref by semver selection.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecfilesindexgitsecretref">secretRef</a></b></td>
        <td>object</td>
        <td>
          Optional credentials for the Git server.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>url</b></td>
        <td>string</td>
        <td>
          Git repository URL (HTTPS or SSH).<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecfilesindexgitverification">verification</a></b></td>
        <td>object</td>
        <td>
          GPG signature verification options.<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.files[index].git.refSelection
<sup><sup>[↩ Parent](#datalabspecfilesindexgit)</sup></sup>



Resolve an explicit ref by semver selection.

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
        <td><b><a href="#datalabspecfilesindexgitrefselectionsemver">semver</a></b></td>
        <td>object</td>
        <td>
          <br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.files[index].git.refSelection.semver
<sup><sup>[↩ Parent](#datalabspecfilesindexgitrefselection)</sup></sup>





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
        <td><b>constraints</b></td>
        <td>string</td>
        <td>
          <br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecfilesindexgitrefselectionsemverprereleases">prereleases</a></b></td>
        <td>object</td>
        <td>
          <br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.files[index].git.refSelection.semver.prereleases
<sup><sup>[↩ Parent](#datalabspecfilesindexgitrefselectionsemver)</sup></sup>





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
        <td><b>identifiers</b></td>
        <td>[]string</td>
        <td>
          <br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.files[index].git.secretRef
<sup><sup>[↩ Parent](#datalabspecfilesindexgit)</sup></sup>



Optional credentials for the Git server.

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
          Name of a Secret with auth (ssh-privatekey/knownhosts or username/password).<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>namespace</b></td>
        <td>string</td>
        <td>
          Namespace of the Secret.<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.files[index].git.verification
<sup><sup>[↩ Parent](#datalabspecfilesindexgit)</sup></sup>



GPG signature verification options.

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
        <td><b><a href="#datalabspecfilesindexgitverificationpublickeyssecretref">publicKeysSecretRef</a></b></td>
        <td>object</td>
        <td>
          <br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.files[index].git.verification.publicKeysSecretRef
<sup><sup>[↩ Parent](#datalabspecfilesindexgitverification)</sup></sup>





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
          Secret containing GPG public keys.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>namespace</b></td>
        <td>string</td>
        <td>
          Namespace of the Secret.<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.files[index].http
<sup><sup>[↩ Parent](#datalabspecfilesindex)</sup></sup>



HTTP source configuration for downloading an asset or archive.

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
        <td><b><a href="#datalabspecfilesindexhttpsecretref">secretRef</a></b></td>
        <td>object</td>
        <td>
          Optional basic-auth credentials for the HTTP server.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>sha256</b></td>
        <td>string</td>
        <td>
          Optional checksum for verification of the downloaded asset.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>url</b></td>
        <td>string</td>
        <td>
          HTTP(S) URL to file or archive; archives are unpacked automatically.<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.files[index].http.secretRef
<sup><sup>[↩ Parent](#datalabspecfilesindexhttp)</sup></sup>



Optional basic-auth credentials for the HTTP server.

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
          Secret containing username/password.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>namespace</b></td>
        <td>string</td>
        <td>
          Namespace of the Secret.<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.files[index].image
<sup><sup>[↩ Parent](#datalabspecfilesindex)</sup></sup>



Container image source configuration.

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
        <td><b>dangerousSkipTLSVerify</b></td>
        <td>boolean</td>
        <td>
          Skip TLS verification when pulling from the registry.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecfilesindeximagesecretref">secretRef</a></b></td>
        <td>object</td>
        <td>
          Optional credentials for the image registry.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecfilesindeximagetagselection">tagSelection</a></b></td>
        <td>object</td>
        <td>
          Optional semantic-version tag selection policy.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>url</b></td>
        <td>string</td>
        <td>
          OCI image reference (e.g., ghcr.io/org/repo:tag or @sha256:...).<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.files[index].image.secretRef
<sup><sup>[↩ Parent](#datalabspecfilesindeximage)</sup></sup>



Optional credentials for the image registry.

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
          Name of a Secret containing registry credentials.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>namespace</b></td>
        <td>string</td>
        <td>
          Namespace of the Secret.<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.files[index].image.tagSelection
<sup><sup>[↩ Parent](#datalabspecfilesindeximage)</sup></sup>



Optional semantic-version tag selection policy.

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
        <td><b><a href="#datalabspecfilesindeximagetagselectionsemver">semver</a></b></td>
        <td>object</td>
        <td>
          <br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.files[index].image.tagSelection.semver
<sup><sup>[↩ Parent](#datalabspecfilesindeximagetagselection)</sup></sup>





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
        <td><b>constraints</b></td>
        <td>string</td>
        <td>
          Semver constraint string.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b><a href="#datalabspecfilesindeximagetagselectionsemverprereleases">prereleases</a></b></td>
        <td>object</td>
        <td>
          <br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.files[index].image.tagSelection.semver.prereleases
<sup><sup>[↩ Parent](#datalabspecfilesindeximagetagselectionsemver)</sup></sup>





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
        <td><b>identifiers</b></td>
        <td>[]string</td>
        <td>
          <br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.quota
<sup><sup>[↩ Parent](#datalabspec)</sup></sup>



Optional per-datalab session quota overrides. If a field is not specified here, the composition falls back to EnvironmentConfig at `spec.defaults.quota`, and then to hard defaults. Effective defaults (when neither XR nor EnvironmentConfig provides a value): memory=2Gi, storage=1Gi, budget=medium.

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
        <td><b>budget</b></td>
        <td>enum</td>
        <td>
          Namespace budget class determining available compute resources. Accepted values correspond to standard Educates resource budgets. Effective default (if not set here or in EnvironmentConfig): "medium".<br/>
          <br/>
            <i>Enum</i>: small, medium, large, x-large, xx-large, xxx-large<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>memory</b></td>
        <td>string</td>
        <td>
          Memory request for the session environment as a Kubernetes quantity (e.g., "2Gi", "512Mi"). Effective default (if not set here or in EnvironmentConfig): "2Gi".<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>storage</b></td>
        <td>string</td>
        <td>
          Storage size for the session as a Kubernetes quantity (e.g., "1Gi"). Effective default (if not set here or in EnvironmentConfig): "1Gi".<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.registry
<sup><sup>[↩ Parent](#datalabspec)</sup></sup>



Optional settings for the in-session Docker registry. When enabled, a registry service is added to the session applications.

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
        <td><b>enabled</b></td>
        <td>boolean</td>
        <td>
          Whether to provision the Docker registry application for this Datalab. Effective default: false.<br/>
          <br/>
            <i>Default</i>: false<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>storage</b></td>
        <td>string</td>
        <td>
          Storage size for the Docker registry data volume as a Kubernetes quantity (e.g., "5Gi", "20Gi"). Effective default: "5Gi".<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>


### Datalab.spec.security
<sup><sup>[↩ Parent](#datalabspec)</sup></sup>



Optional per-datalab session security settings. If a field is not specified here, the composition falls back to EnvironmentConfig at `spec.defaults.security`, and then to hard defaults. Effective defaults (when neither XR nor EnvironmentConfig provides a value): policy=baseline, kubernetesAccess=true, kubernetesRole=edit. When policy is "privileged", Docker is automatically enabled with 20Gi storage.

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
        <td><b>kubernetesAccess</b></td>
        <td>boolean</td>
        <td>
          Whether a Kubernetes service account token should be made available within the session. Effective default (if not set here or in EnvironmentConfig): true.<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>kubernetesRole</b></td>
        <td>enum</td>
        <td>
          Session namespace RBAC role. Accepted values: "admin", "edit", "view". Effective default (if not set here or in EnvironmentConfig): "edit".<br/>
          <br/>
            <i>Enum</i>: admin, edit, view<br/>
        </td>
        <td>false</td>
      </tr><tr>
        <td><b>policy</b></td>
        <td>enum</td>
        <td>
          Pod Security Standard policy level. Accepted values: "restricted", "baseline", "privileged". Effective default (if not set here or in EnvironmentConfig): "baseline".<br/>
          <br/>
            <i>Enum</i>: restricted, baseline, privileged<br/>
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


### Datalab.spec.vectorStores[key]
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
          Storage size for Qdrant persistent data volume as a Kubernetes quantity (e.g., "1Gi", "10Gi"). Effective default: "1Gi".<br/>
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
        <td><b><a href="#datalabstatussessionskey">sessions</a></b></td>
        <td>map[string]object</td>
        <td>
          Map of session IDs and their current state.<br/>
        </td>
        <td>false</td>
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
        <td><b>url</b></td>
        <td>string</td>
        <td>
          Public URL of the active session.<br/>
        </td>
        <td>false</td>
      </tr></tbody>
</table>
