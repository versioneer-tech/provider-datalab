# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import base64
import hashlib
import json
from composition.helpers import (
    _resource_name,
    _to_dict,
    _vcluster_groups,
    _vcluster_profile,
)
from composition.render import _render_template

CREDENTIAL_HELPER = '#!/usr/bin/env python3\n# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)\n# SPDX-License-Identifier: Apache-2.0\n\n"""Use a caller\'s access token or request one with the Datalab OAuth client."""\n\nimport argparse\nimport base64\nfrom datetime import datetime, timedelta, timezone\nimport json\nimport os\nfrom pathlib import Path\nimport ssl\nimport sys\nfrom urllib.error import HTTPError, URLError\nfrom urllib.parse import urlencode\nfrom urllib.request import Request, urlopen\n\n\ndef main():\n    parser = argparse.ArgumentParser(description=__doc__)\n    parser.add_argument(\'--issuer\', required=True)\n    parser.add_argument(\'--client-id\', required=True)\n    source = parser.add_mutually_exclusive_group()\n    source.add_argument(\'--access-token-file\', default=os.environ.get(\'DATALAB_ACCESS_TOKEN_FILE\'))\n    source.add_argument(\'--client-secret-file\', default=os.environ.get(\'DATALAB_CLIENT_SECRET_FILE\'))\n    source.add_argument(\'--client-secret-env\')\n    parser.add_argument(\'--issuer-ca\')\n    parser.add_argument(\'--issuer-ca-data\')\n    args = parser.parse_args()\n    if sum(bool(value) for value in (args.access_token_file, args.client_secret_file, args.client_secret_env)) != 1:\n        parser.error(\'Supply one access token file or client secret source. Set DATALAB_ACCESS_TOKEN_FILE or DATALAB_CLIENT_SECRET_FILE.\')\n    if not args.issuer.startswith(\'https://\'):\n        parser.error(\'--issuer must use HTTPS\')\n    try:\n        if args.access_token_file:\n            status = {\'token\': Path(args.access_token_file).read_text().strip()}\n        else:\n            secret = (Path(args.client_secret_file).read_text().strip() if args.client_secret_file\n                      else os.environ[args.client_secret_env])\n            if not secret:\n                raise ValueError(\'Empty client secret\')\n            ca_data = base64.b64decode(args.issuer_ca_data).decode() if args.issuer_ca_data else None\n            context = ssl.create_default_context(cafile=args.issuer_ca, cadata=ca_data)\n            request = Request(args.issuer.rstrip(\'/\') + \'/protocol/openid-connect/token\',\n                              data=urlencode({\'grant_type\': \'client_credentials\', \'client_id\': args.client_id,\n                                              \'client_secret\': secret}).encode())\n            with urlopen(request, context=context, timeout=30) as result:\n                token = json.load(result)\n            expires = datetime.now(timezone.utc) + timedelta(seconds=int(token[\'expires_in\']) - 10)\n            status = {\'token\': token[\'access_token\'], \'expirationTimestamp\': expires.isoformat().replace(\'+00:00\', \'Z\')}\n        if not status[\'token\']:\n            raise ValueError(\'Empty access token\')\n        credential = {\n            \'apiVersion\': \'client.authentication.k8s.io/v1\', \'kind\': \'ExecCredential\',\n            \'status\': status,\n        }\n    except (OSError, HTTPError, URLError, ValueError, KeyError):\n        print(\'Could not obtain a Datalab API token. Check the token file or issuer and client credential.\', file=sys.stderr)\n        return 1\n    print(json.dumps(credential))\n    return 0\n\n\nif __name__ == \'__main__\':\n    sys.exit(main())\n'


def compose(req, rsp):
    xr = _to_dict(req.observed.composite.resource)
    spec = xr.get("spec") or {}
    status = (
        _to_dict(rsp.desired.composite.resource).get("status") or xr.get("status") or {}
    )
    instances = spec.get("vclusters") or {}
    if not instances and not any(
        c.get("type") == "vcluster" for c in status.get("connections", [])
    ):
        return
    meta = xr["metadata"]
    name = meta["name"]
    namespace = meta.get("namespace") or "default"
    env = _to_dict(req.context).get("apiextensions.crossplane.io/environment") or {}
    connections = [
        c for c in status.get("connections", []) if c.get("type") != "vcluster"
    ]

    def ready(key):
        observed = req.observed.resources.get(key)
        body = _to_dict(observed.resource) if observed else {}
        return any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in body.get("status", {}).get("conditions", [])
        )

    for instance, config in sorted(instances.items()):
        endpoint = f"https://{name}.{env['ingress']['domain']}/.{instance}"
        cluster = {"server": endpoint}
        gateway_ca = (env.get("ingress") or {}).get("certificateAuthority")
        if gateway_ca:
            cluster["certificate-authority-data"] = base64.b64encode(
                gateway_ca.encode()
            ).decode()
        issuer = str((env.get("iam") or {})["issuerURL"]).rstrip("/")
        for group in _vcluster_groups(config):
            profile = _vcluster_profile(name, instance, group["name"])
            connection_name = _resource_name("vcluster", instance, group["name"])
            # New names let Crossplane delete old Secrets with stored credentials.
            secret_name = _resource_name(name, "vcluster", instance, group["name"], "connection")
            args = [
                "-c",
                CREDENTIAL_HELPER,
                "--issuer",
                issuer,
                "--client-id",
                name,
            ]
            issuer_ca = (env.get("vcluster") or {}).get("issuerCA")
            if issuer_ca:
                args += [
                    "--issuer-ca-data",
                    base64.b64encode(issuer_ca.encode()).decode(),
                ]
            binding = hashlib.sha256(
                f"{group['name']}:{group['namespace']}:{group['role']}".encode()
            ).hexdigest()[:12]
            scope_resource = (
                _resource_name(name, "interactive") if group["name"] == "cluster-admin"
                else _resource_name(profile, "scope")
            )
            complete = all(
                ready(key)
                for key in [
                    *(
                        _resource_name("vcluster", name, instance, suffix)
                        for suffix in ("statefulset", "route", "backend-tls")
                    ),
                    _resource_name(
                        "vcluster", name, instance, "access", f"binding-{binding}"
                    ),
                    f"keycloak-client-{name}",
                    f"keycloak-vcluster-role-{profile}",
                    f"keycloak-optional-scope-{scope_resource}",
                    "keycloak-optional-role-" + _resource_name(scope_resource, profile),
                    f"keycloak-defaultScopes-{name}",
                    f"keycloak-optionalScopes-{name}",
                    "keycloak-selected-role-" + _resource_name(scope_resource, profile),
                    f"keycloak-selected-role-{name}-ws-api",
                    f"keycloak-selected-roles-{name}",
                ]
            )
            kubeconfig = _render_template(
                req,
                "vcluster/client-config",
                name=_resource_name(name, instance),
                cluster=cluster,
                profile=profile,
                contexts_0_context_namespace=(
                    "default" if group["namespace"] == "*" else group["namespace"]
                ),
                args=args,
            )
            key = _resource_name("connection", secret_name)
            rsp.desired.resources[key].resource.update(
                _render_template(
                    req,
                    "secrets/connection",
                    key=key,
                    name=name,
                    namespace=namespace,
                    secret_name=secret_name,
                    connection_name=connection_name,
                    values={key: base64.b64encode(value.encode()).decode() for key, value in {
                        "kubeconfig": json.dumps(kubeconfig, indent=2, sort_keys=True),
                        "client-id": name,
                        "issuer-url": issuer,
                    }.items()},
                )
            )
            connections.append(
                {
                    "name": connection_name,
                    "type": "vcluster",
                    "instance": instance,
                    "group": group["name"],
                    "targetNamespace": group["namespace"],
                    "role": group["role"],
                    "endpoint": endpoint,
                    "ready": complete,
                    "secretRef": {"name": secret_name, "namespace": namespace},
                }
            )
    status["connections"] = connections
    rsp.desired.composite.resource.update({"status": status})
