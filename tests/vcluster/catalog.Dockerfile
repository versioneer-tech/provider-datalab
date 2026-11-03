# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

FROM python:3.13-slim
RUN pip install --no-cache-dir 'stac-fastapi-pgstac[server]==7.2.1' 'pypgstac[psycopg]==0.10.0' 'psycopg[binary,pool]'
COPY tests/vcluster/migrate.py /opt/catalog/migrate.py
USER 1000:1000
CMD ["uvicorn", "stac_fastapi.pgstac.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
