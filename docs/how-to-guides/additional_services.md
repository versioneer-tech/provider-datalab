# Additional services

Run services such as Dask or MLflow as Kubernetes workloads from your Datalab
terminal. These examples need Kubernetes API access and permission to create
Pods, Deployments, Services, and PVCs in the target namespace.

Use a vCluster for tools that need their own CRDs, controllers, or cluster
roles. For a short-lived process, you can run it in the terminal and use the
editor's Ports tab to open its web interface.

For PostgreSQL, MongoDB, Redis, Qdrant, and a registry, first check whether the
[managed service fields](usage_concepts.md) meet your needs. The platform
operator maintains those services and their backups.

## Dask

Dask runs tasks across a scheduler and workers. This example creates one
scheduler and one worker in the current namespace. Connect to the scheduler
from Python with `dask.distributed.Client`.

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
Open the scheduler dashboard through the editor's Ports tab:

```bash
kubectl port-forward svc/dask-scheduler 8787:8787
```

Dask Gateway also needs cluster-wide resources. Use a vCluster or ask the
operator to install it. With the `dask` Helm repository configured, run:

```bash
helm repo update
helm upgrade --install dask-gateway dask/dask-gateway \
  -n "${DEFAULT_NAMESPACE:-default}" \
  --create-namespace \
  --set gateway.auth.type=simple \
  --set gateway.auth.simple.password='' \
  --set traefik.service.type=ClusterIP \
  --set gateway.backend.image.name=ghcr.io/dask/dask-gateway \
  --set gateway.backend.image.tag=2025.4.0 \
  --wait --atomic
```


## MLflow

MLflow records experiment runs and their artifacts. This example stores its
SQLite database on a PVC and artifacts in an existing S3 bucket. Set `BUCKET`
to a bucket your Datalab can write to.

The PVC belongs to the current namespace. Check namespace deletion rules and
the volume's reclaim policy before using it for records you need to keep. For a shared service,
use a managed database and arrange artifact backups with the operator.

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
Open the MLflow interface through the editor's Ports tab:

```bash
kubectl port-forward svc/mlflow 5000:5000
```

Point your code at the forwarded tracking server:

```bash
export MLFLOW_TRACKING_URI="http://127.0.0.1:5000"
```


## PostgreSQL with psql

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

Attach to the Pod after it starts:

```bash
kubectl attach -it pgsql-debug
```

Use psql to create and query a test table:

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


## Keep or remove a service

Remove test services when the experiment ends. Before keeping one, agree with
the platform team on its storage, backups, monitoring, upgrades, and deletion.
Back up the service data separately from the session volume.
