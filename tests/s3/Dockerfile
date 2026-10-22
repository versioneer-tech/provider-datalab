# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

FROM python:3.13-slim
RUN pip install --no-cache-dir boto3==1.42.0
COPY tests/s3/s3-credentials.py /test/s3-credentials.py
COPY tests/s3/e2e.py /test/e2e.py
CMD ["sleep", "infinity"]
