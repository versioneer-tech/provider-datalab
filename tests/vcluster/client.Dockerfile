# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

FROM python:3.13-slim
RUN pip install --no-cache-dir 'grpcio-tools==1.85.1'
COPY tests/vcluster/process.proto /tmp/process.proto
RUN mkdir -p /opt/sandbox && python -m grpc_tools.protoc -I/tmp --python_out=/opt/sandbox --grpc_python_out=/opt/sandbox /tmp/process.proto
CMD ["sleep", "infinity"]
