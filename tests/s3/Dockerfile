# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

FROM python:3.13-slim@sha256:7249d5587b78209a006dc4a3b5340678f84ea729239193aa559962cd8c1fce50
COPY tests/s3/requirements.txt /test/requirements.txt
RUN pip install --no-cache-dir --only-binary=:all: --require-hashes -r /test/requirements.txt
COPY tests/s3/s3-credentials.py /test/s3-credentials.py
COPY tests/s3/e2e.py /test/e2e.py
CMD ["sleep", "infinity"]
