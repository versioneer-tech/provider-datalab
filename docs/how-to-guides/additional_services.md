# Additional Services

This section explains how end users can **extend** the default `provider-datalab` capabilities by deploying additional services and tools that support their daily workflows.

A `Datalab` environment provides a preconfigured **VS Code Server** with a persistent file system and access to the connected object storage, along with essential CLI tools such as `git`, `curl`, `aws`, or `rclone`.  
While this already covers many data exploration and transformation needs, users often require more specialized tooling — for example, dashboards for visualization, services for experiment tracking, or out-of-process compute backends for scalable data processing.

Although many of these tools can be started directly from the integrated terminal and exposed via VS Code’s port forwarding feature, that approach tends to be **fragile and transient** - you must carefully manage Python environments, avoid breaking dependencies during upgrades, and remember that the terminal session lifetime is temporary.

A more robust approach is to deploy such services **as native Kubernetes applications** — directly from within the Datalab. Because each Datalab session has access to the Kubernetes API (depending on the operator configuration), users can deploy workloads within their assigned namespace or, when running in **vCluster** mode, inside a **fully isolated virtual cluster** with their own CRDs, RBAC rules, and controllers.  This enables running even complex frameworks that typically require cluster-wide resources — for example, a Dask Gateway.

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
> Once the Datalab is deleted, the PVC and stored data will also be removed unless your operator configures a persistent storage backend.

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
          image: ghcr.io/mlflow/mlflow:latest
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

## Summary

In its current form, `provider-datalab` focuses on deploying **ephemeral or stateless services** on Kubernetes in a seamless and reproducible way. These services are tied to the Datalab session lifecycle, ensuring automatic cleanup and cost efficiency when sessions are terminated.

However, if your operator provides additional storage capabilities — for example:

- persistent block storage (via Kubernetes `StorageClass`)
- relational databases (PostgreSQL, MySQL)
- key–value stores (Redis, etcd)

then more complex, stateful workloads can also be supported. Such setups, however, come with additional maintenance effort and require clear alignment of responsibilities between operators and end users.  Making these integrations easier and more declarative is planned for future releases.
