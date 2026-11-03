# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Install PgSTAC and give the catalog API a separate database login."""

import os
import subprocess
import sys

import psycopg
from psycopg import sql


def main():
    result = subprocess.run(["pypgstac", "migrate"], capture_output=True)
    if result.returncode:
        sys.exit("Catalog schema migration failed.")
    with psycopg.connect("") as connection:
        # The migration credential is not used by the running API.
        connection.execute(
            sql.SQL("CREATE ROLE catalog LOGIN PASSWORD {}").format(
                sql.Literal(os.environ["CATALOG_PASSWORD"])
            )
        )
        connection.execute("GRANT pgstac_ingest TO catalog")
    print("Catalog schema and application login are ready.")


if __name__ == "__main__":
    main()
