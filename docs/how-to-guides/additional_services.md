# Additional Services

You can add services to a Datalab for tasks such as distributed computing or experiment tracking. This guide shows how to deploy Dask and MLflow from your workspace.

A `Datalab` environment provides a preconfigured **VS Code Server** with a persistent file system and access to the connected object storage, along with essential CLI tools such as `git`, `curl`, `aws`, or `rclone`.
You can add dashboards, experiment tracking, or separate compute workloads as needed.

For a short experiment, start a tool in the terminal and use VS Code port forwarding to open it. For services that must keep running, use Kubernetes workloads with their own dependencies and storage.

Deploy these services **as native Kubernetes applications** when the operator
has allowed Kubernetes API access. Users can deploy workloads in their assigned
namespace or, in **vCluster** mode, in a virtual control plane with its own
CRDs, RBAC rules, and controllers. This supports frameworks that need
cluster-wide resources, such as Dask Gateway, without giving users access to
the host cluster.

For data that needs backups and maintenance, use the managed service fields where possible: `spec.databases`, `spec.documentStores`, `spec.cacheStores`, `spec.vectorStores`, and `spec.registry`. Create object-storage buckets through [Provider Storage](https://provider-storage.versioneer.at/) or your platform's storage process, then pass their credentials to Provider Datalab.

> **Note:** The `kubectl` and `helm` CLIs are preinstalled as well. You can apply manifests, install Helm charts, and inspect Kubernetes resources directly from the terminal.

---

## Example: Deploying a Dask Cluster

The following example shows how to start a simple Dask scheduler and worker deployment directly inside your Datalab namespace.
This provides a minimal distributed compute backend that you can connect to from Python via `dask.distributed.Client`.

<details>
<summary><strong>Click to expand: Deploy Dask</strong></summary>

```bash
kubectl apply -f - <<'EOF'
---
apiVersion: v1
kind: Service
metadata:
  name: dask-scheduler
spec:
  selector:
    app: dask-scheduler
  ports:
    - name: tcp-scheduler
      port: 8786
      targetPort: 8786
    - name: http-dashboard
      port: 8787
      targetPort: 8787
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dask-scheduler
spec:
  replicas: 1
  selector:
    matchLabels:
      app: dask-scheduler
  template:
    metadata:
      labels:
        app: dask-scheduler
    spec:
      containers:
        - name: scheduler
          image: daskdev/dask:2025.4.0
          args: ["dask-scheduler", "--dashboard-address", ":8787"]
          ports:
            - containerPort: 8786
            - containerPort: 8787
          resources:
            requests: {cpu: "500m", memory: "1Gi"}
            limits:   {cpu: "1",    memory: "2Gi"}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dask-worker
spec:
  replicas: 1
  selector:
    matchLabels:
      app: dask-worker
  template:
    metadata:
      labels:
        app: dask-worker
    spec:
      containers:
        - name: worker
          image: daskdev/dask:2025.4.0
          args: ["dask-worker", "tcp://dask-scheduler:8786", "--nthreads", "2", "--memory-limit", "2GB"]
          resources:
            requests: {cpu: "500m", memory: "1Gi"}
            limits:   {cpu: "1",    memory: "2Gi"}
EOF
```
</details>

Once running, you can port-forward and use the VS Code **Ports** tab to explore the Dask dashboard:
```bash
kubectl port-forward svc/dask-scheduler 8787:8787
```

You can also deploy **Dask Gateway** via Helm — this is only possible in **vCluster** mode, since it requires cluster-wide resources such as CRDs and RBAC cluster roles:

```bash
helm repo update
helm upgrade --install dask-gateway dask/dask-gateway   -n "${DEFAULT_NAMESPACE:-default}"   --create-namespace   --set gateway.auth.type=simple   --set gateway.auth.simple.password=''   --set traefik.service.type=ClusterIP   --set gateway.backend.image.name=ghcr.io/dask/dask-gateway   --set gateway.backend.image.tag=2025.4.0   --wait --atomic
```

---

## Example: Deploying MLflow with Persistent Storage

`MLflow` is a popular experiment-tracking platform that complements data exploration workflows.
The following example deploys an MLflow server together with a simple SQLite backend and a `PersistentVolumeClaim` for artifact and metadata storage.

> **Note:** The PVC is bound to your Datalab session.
> Once the Datalab is deleted, the PVC and stored data will also be removed unless your operator configures a persistent storage backend. For durable MLflow metadata or artifacts, use a managed database and an object-storage bucket provisioned outside Provider Datalab, for example with Provider Storage.

<details>
<summary><strong>Click to expand: Deploy MLflow</strong></summary>

```bash
export BUCKET=ws-frank # replace accordingly

kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: minio-creds
type: Opaque
stringData:
  accessKey: "${AWS_ACCESS_KEY_ID}"
  secretKey: "${AWS_SECRET_ACCESS_KEY}"
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: minio-config
data:
  endpoint: "${AWS_ENDPOINT_URL}"
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: mlflow
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 1Gi
---
apiVersion: v1
kind: Service
metadata:
  name: mlflow
spec:
  selector:
    app: mlflow
  ports:
    - name: http
      port: 5000
      targetPort: 5000
      protocol: TCP
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mlflow
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mlflow
  template:
    metadata:
      labels:
        app: mlflow
    spec:
      containers:
        - name: mlflow
          image: ghcr.io/mlflow/mlflow:v3.14.0
          command: ["/bin/sh","-lc"]
          args:
            - |
              python -m pip install --no-cache-dir --upgrade pip &&
              pip install --no-cache-dir boto3 &&
              exec mlflow server \
                --backend-store-uri sqlite:////mlflow/mlflow.db \
                --serve-artifacts \
                --artifacts-destination s3://"${BUCKET}"/mlruns \
                --host 0.0.0.0 --port 5000 \
                --workers 2 \
                --allowed-hosts '*' \
                --cors-allowed-origins '*'
          ports:
            - containerPort: 5000
          resources:
            requests: { cpu: "100m", memory: "512Mi" }
            limits:   { cpu: "300m", memory: "2Gi" }
          env:
            - name: MLFLOW_S3_ENDPOINT_URL
              valueFrom:
                configMapKeyRef: { name: minio-config, key: endpoint }
            - name: AWS_ACCESS_KEY_ID
              valueFrom:
                secretKeyRef: { name: minio-creds, key: accessKey }
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom:
                secretKeyRef: { name: minio-creds, key: secretKey }
            - name: AWS_S3_FORCE_PATH_STYLE
              value: "true"
            - name: AWS_EC2_METADATA_DISABLED
              value: "true"
          volumeMounts:
            - name: data
              mountPath: /mlflow
          readinessProbe:
            httpGet: { path: "/", port: 5000 }
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet: { path: "/", port: 5000 }
            initialDelaySeconds: 20
            periodSeconds: 20
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: mlflow
EOF
```
</details>

Once running, you can port-forward and use the VS Code **Ports** tab to explore the MLflow UI:
```bash
kubectl port-forward svc/mlflow 5000:5000
```

To use **MLflow** in your code, you need to connect to the tracking server running at `http://localhost:5000`. This can be done by setting the following environment variable:

```bash
export MLFLOW_TRACKING_URI="http://127.0.0.1:5000"
```

---

## Example: Using psql to access and work with a managed database

If your Datalab provides database credentials through
`POSTGRES_<HOST>_<DATABASE>_URL_EXTERNAL` environment variables, you can
connect to the managed PostgreSQL instance by starting a Pod that opens a
`psql` shell.

```bash
envsubst <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: pgsql-debug
spec:
  restartPolicy: Never
  containers:
  - name: psql
    image: postgres:17
    stdin: true
    tty: true
    command:
      - sh
      - -lc
      - |
        exec psql "$POSTGRES_URL_EXTERNAL"
    env:
      - name: POSTGRES_URL_EXTERNAL
        value: ${POSTGRES_PG0_DEV_URL_EXTERNAL}
EOF
```

Now attach to the pod.

```bash
kubectl attach -it pgsql-debug
```

And run your `psql` commands.

```sql
\set ON_ERROR_STOP on
\l

DROP TABLE IF EXISTS demo;

CREATE TABLE demo (
    id serial PRIMARY KEY,
    name text,
    created_at timestamptz DEFAULT now(),
    meta jsonb
);

INSERT INTO demo (name, meta) VALUES
('alpha', '{"type":"test","value":1}'),
('beta',  '{"type":"test","value":2}'),
('gamma', '{"type":"prod","value":3}');

SELECT * FROM demo;
```

---

## Keeping Services and Data

Choose how to manage a service based on how long you need it:

- **Temporary services**, such as the Dask and MLflow examples above, are useful for experiments. Remove them when the work is complete.
- **Managed services** requested through the `Datalab` spec need backup, monitoring, upgrade, and deletion policies. Agree on these with the platform team before you store data that must be kept.

If you need a service after the experiment ends, agree with the platform team on how to maintain it and recover its data.
