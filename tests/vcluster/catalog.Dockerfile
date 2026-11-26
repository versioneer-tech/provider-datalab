# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

FROM python:3.13-slim@sha256:7249d5587b78209a006dc4a3b5340678f84ea729239193aa559962cd8c1fce50
COPY tests/vcluster/tooling/requirements.txt /opt/catalog/build-requirements.txt
RUN pip install --no-cache-dir --only-binary=:all: --require-hashes -r /opt/catalog/build-requirements.txt
COPY tests/vcluster/requirements.txt /opt/catalog/requirements.txt
# version-parser has no wheel. Its fixed source and setup.py are reviewed.
RUN pip install --no-cache-dir --only-binary=:all: --no-binary=version-parser \
    --no-build-isolation --require-hashes -r /opt/catalog/requirements.txt
COPY tests/vcluster/initialize.py /opt/catalog/initialize.py
USER 1000:1000
CMD ["uvicorn", "stac_fastapi.pgstac.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
