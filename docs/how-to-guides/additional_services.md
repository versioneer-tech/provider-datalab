# Additional services

Run services such as Dask or MLflow through a [virtual cluster profile](vcluster.md).
Set `KUBECONFIG` to its downloaded file. These examples need permission to
create Pods, Deployments, Services, and PVCs in the target virtual namespace.
Use port forwarding to open a workload's web interface.

Use the [Datalab service fields](usage_concepts.md#postgresql) for managed
PostgreSQL and Valkey stores. The environment also supplies
a [shared OCI registry](usage_concepts.md#oci-registry).

The MLflow and psql examples below use virtual namespace `demo` and these
[Secret bindings](connections.md#bind-a-connection). Add them to the Datalab's
existing `vc0` configuration. The PostgreSQL example also needs `pg0` with a
`dev` database, as in the [Jeff example](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/002-lab.yaml).

```yaml
spec:
  vclusters:
    vc0:
      secretBindings:
      - type: s3
        name: primary
        target:
          namespace: demo
          name: mlflow-storage
      - type: postgres
        name: pg0
        target:
          namespace: demo
          name: postgres-credentials
```

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
          startupProbe:
            httpGet: {path: /health, port: 8787}
            periodSeconds: 5
            failureThreshold: 60
          readinessProbe:
            httpGet: {path: /health, port: 8787}
          livenessProbe:
            httpGet: {path: /health, port: 8787}
            periodSeconds: 20
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
          args: ["dask-worker", "tcp://dask-scheduler:8786", "--nthreads", "2", "--memory-limit", "2GB", "--dashboard-address", ":8789"]
          ports:
            - containerPort: 8789
          startupProbe:
            httpGet: {path: /health, port: 8789}
            periodSeconds: 5
            failureThreshold: 60
          readinessProbe:
            httpGet: {path: /health, port: 8789}
          livenessProbe:
            httpGet: {path: /health, port: 8789}
            periodSeconds: 20
          resources:
            requests: {cpu: "500m", memory: "1Gi"}
            limits:   {cpu: "1",    memory: "2Gi"}
EOF
```

Open the scheduler dashboard with port forwarding:

```bash
kubectl port-forward svc/dask-scheduler 8787:8787
```

Dask Gateway needs cluster-wide permissions. Use a virtual cluster
administrator profile or ask the operator to install it:

```bash
helm repo add dask https://helm.dask.org
helm repo update
helm install dask-gateway dask/dask-gateway \
  --version 2025.4.0 \
  -n dask-gateway \
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
to a bucket your Datalab can write to. The bound `mlflow-storage` Secret must
contain `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY`.

The PVC belongs to `demo`. Check namespace deletion rules and
the volume's reclaim policy before storing records you need to keep.
The Deployment stops the old Pod before an update so only one Pod uses SQLite.
For a shared service, use a managed database and arrange artifact backups
with the operator.

```bash
export BUCKET=s-jeff

kubectl -n demo apply -f - <<EOF
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
  strategy:
    type: Recreate
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
              pip install --no-cache-dir boto3 &&
              exec mlflow server \
                --backend-store-uri sqlite:////mlflow/mlflow.db \
                --serve-artifacts \
                --artifacts-destination s3://"${BUCKET}"/mlruns \
                --host 0.0.0.0 --port 5000 \
                --workers 2
          ports:
            - containerPort: 5000
          resources:
            requests: { cpu: "100m", memory: "512Mi" }
            limits:   { cpu: "300m", memory: "2Gi" }
          env:
            - name: MLFLOW_S3_ENDPOINT_URL
              valueFrom:
                secretKeyRef: { name: mlflow-storage, key: AWS_ENDPOINT_URL }
            - name: AWS_ACCESS_KEY_ID
              valueFrom:
                secretKeyRef: { name: mlflow-storage, key: AWS_ACCESS_KEY_ID }
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom:
                secretKeyRef: { name: mlflow-storage, key: AWS_SECRET_ACCESS_KEY }
            - name: AWS_SESSION_TOKEN
              valueFrom:
                secretKeyRef: { name: mlflow-storage, key: AWS_SESSION_TOKEN, optional: true }
            - name: AWS_S3_FORCE_PATH_STYLE
              value: "true"
            - name: AWS_EC2_METADATA_DISABLED
              value: "true"
          volumeMounts:
            - name: data
              mountPath: /mlflow
          startupProbe:
            httpGet: {path: /, port: 5000}
            periodSeconds: 5
            failureThreshold: 120
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

Open MLflow with port forwarding:

```bash
kubectl -n demo port-forward svc/mlflow 5000:5000
```

Point your code at the forwarded tracking server:

```bash
export MLFLOW_TRACKING_URI="http://127.0.0.1:5000"
```

## PostgreSQL with psql

Create a psql Pod that reads the bound `postgres-credentials` Secret:

```bash
kubectl -n demo apply -f - <<'EOF'
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
    command: ["psql", "--dbname=dev"]
    env:
    - name: PGHOST
      valueFrom:
        secretKeyRef: {name: postgres-credentials, key: host}
    - name: PGPORT
      valueFrom:
        secretKeyRef: {name: postgres-credentials, key: port}
    - name: PGUSER
      valueFrom:
        secretKeyRef: {name: postgres-credentials, key: user}
    - name: PGPASSWORD
      valueFrom:
        secretKeyRef: {name: postgres-credentials, key: password}
EOF
```

Attach to the Pod after it starts:

```bash
kubectl -n demo attach -it pgsql-debug
```

Check the connection with a temporary table:

```sql
\set ON_ERROR_STOP on
CREATE TEMP TABLE datalab_check (value text);
INSERT INTO datalab_check VALUES ('ready');
SELECT value FROM datalab_check;
```

## Keep or remove a service

Remove test services when the experiment ends. Before keeping one, agree with
the platform team on its storage, backups, monitoring, maintenance, and deletion.
Back up the service data and any application volumes. These examples create
application PVCs inside the virtual cluster; configure their backups separately.
[Named volumes](volumes.md) provide host PVCs and snapshot schedules, with a
separate lifecycle. Bind a named volume to the virtual namespace when the
application needs its storage and backup policy.
