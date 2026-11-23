# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check caller tokens, device login, refresh, and private caches."""

import base64
import json
import runpy
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from helpers import ROOT


class VclusterCredentialTests(unittest.TestCase):
    def setUp(self):
        self.now = 1900000000
        self.requests = []
        self.sleeps = []
        self.prompts = []

    def access_token(self, exp=None):
        payload = base64.urlsafe_b64encode(json.dumps({"exp": exp or self.now + 300}).encode()).decode().rstrip("=")
        return "header." + payload + ".signature"

    def response(self, *values):
        from urllib.error import HTTPError
        from urllib.parse import parse_qs
        responses = iter(values)

        def request(request, **kwargs):
            self.requests.append((request.full_url, parse_qs(request.data.decode())))
            value = next(responses)
            if "error" in value:
                raise HTTPError(request.full_url, 400, "Bad request", {}, StringIO(json.dumps(value)))
            return StringIO(json.dumps(value))
        return request

    def device(self, **values):
        return {"device_code": "test-device", "user_code": "TEST-CODE", "expires_in": 60,
                "interval": 1, "verification_uri": "https://identity.example/device", **values}

    def run_helper(self, files, response=None, args=(), interactive=False, prompt=None):
        module = runpy.run_path(str(ROOT / "scripts/vcluster-credentials.py"))
        output, error = StringIO(), StringIO()
        argv = ["credentials.py", "--issuer", "https://identity.example/realms/test", "--client-id", "s-joe", *args]

        def sleep(seconds):
            self.sleeps.append(seconds)
            self.now += seconds

        def secret_prompt(message, **kwargs):
            self.prompts.append(message)
            if prompt is None:
                raise AssertionError('Unexpected client secret prompt')
            return prompt() if callable(prompt) else prompt

        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory, \
                patch.object(sys, "argv", argv), \
                patch.object(module["os"], "environ", {"DATALAB_TOKEN_CACHE_DIR": directory, **files}), \
                patch.dict(module["main"].__globals__, {"urlopen": response, "getpass": secret_prompt}), \
                patch.object(sys.stdin, "isatty", return_value=interactive), \
                patch.object(module["time"], "time", lambda: self.now), \
                patch.object(module["time"], "monotonic", lambda: self.now), \
                patch.object(module["time"], "sleep", sleep), \
                redirect_stdout(output), redirect_stderr(error):
            try:
                code = module["main"]()
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), error.getvalue()

    def test_profile_requires_a_separate_credential_source(self):
        code, output, error = self.run_helper({})
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")
        self.assertIn("DATALAB_ACCESS_TOKEN_FILE", error)

    def test_human_token_is_used_without_an_identity_exchange(self):
        with TemporaryDirectory(prefix="test-vcluster-access-token-") as directory:
            token = Path(directory) / "access-token"
            value = self.access_token()
            token.write_text(value + "\n")
            code, output, _ = self.run_helper({"DATALAB_ACCESS_TOKEN_FILE": str(token)})
        self.assertEqual(code, 0)
        status = json.loads(output)["status"]
        self.assertEqual(status["token"], value)
        self.assertIn("expirationTimestamp", status)

    def test_device_login_uses_user_authorization_and_caches_private_tokens(self):
        value = self.access_token()
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            secret = Path(directory) / "client-secret"
            secret.write_text("separate-client-secret\n")
            cache = Path(directory) / "cache"
            files = {"DATALAB_CLIENT_SECRET_FILE": str(secret), "DATALAB_TOKEN_CACHE_DIR": str(cache)}
            code, output, error = self.run_helper(files, self.response(
                self.device(), {"error": "authorization_pending"}, {"error": "slow_down"},
                {"access_token": value, "expires_in": 300, "refresh_token": "test-refresh"},
            ))
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["status"]["token"], value)
            self.assertIn("https://identity.example/device", error)
            self.assertIn("TEST-CODE", error)
            self.assertNotIn("test-refresh", output + error)
            self.assertNotIn("separate-client-secret", output + error)
            self.assertEqual(self.sleeps, [1, 1, 6])
            self.assertEqual(cache.stat().st_mode & 0o777, 0o700)
            cached = list(cache.glob("*.json"))
            self.assertEqual(len(cached), 1)
            self.assertEqual(cached[0].stat().st_mode & 0o777, 0o600)
            self.assertNotIn("separate-client-secret", cached[0].read_text())
            code, output, error = self.run_helper(files)
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["status"]["token"], value)
            self.assertEqual(error, "")
        device_url, authorization = self.requests[0]
        self.assertTrue(device_url.endswith("/auth/device"))
        self.assertEqual(authorization, {
            "client_id": ["s-joe"], "client_secret": ["separate-client-secret"],
            "scope": ["offline_access openid s-joe:interactive"],
        })
        for _, request in self.requests[1:]:
            self.assertEqual(request["grant_type"], ["urn:ietf:params:oauth:grant-type:device_code"])
            self.assertEqual(request["device_code"], ["test-device"])
            self.assertEqual(request["client_secret"], ["separate-client-secret"])

    def test_expired_access_token_refreshes_without_device_login(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            files = {"DATALAB_CLIENT_SECRET_VALUE": "test-secret", "DATALAB_TOKEN_CACHE_DIR": directory}
            args = ["--client-secret-env", "DATALAB_CLIENT_SECRET_VALUE"]
            code, _, error = self.run_helper(files, self.response(self.device(), {
                "access_token": self.access_token(), "expires_in": 300, "refresh_token": "old-refresh",
            }), args)
            self.assertEqual(code, 0, error)
            self.now += 400
            value = self.access_token()
            code, output, error = self.run_helper(files, self.response({
                "access_token": value, "expires_in": 300, "refresh_token": "new-refresh",
            }), args)
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["status"]["token"], value)
            self.assertEqual(error, "")
            self.assertEqual(json.loads(next(Path(directory).glob("*.json")).read_text())["refresh_token"], "new-refresh")
        self.assertEqual(self.requests[-1][1]["grant_type"], ["refresh_token"])
        self.assertEqual(self.requests[-1][1]["refresh_token"], ["old-refresh"])

    def test_rejected_refresh_starts_new_login_and_discards_old_refresh_token(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            files = {"DATALAB_CLIENT_SECRET_VALUE": "test-secret", "DATALAB_TOKEN_CACHE_DIR": directory}
            args = ["--client-secret-env", "DATALAB_CLIENT_SECRET_VALUE"]
            self.run_helper(files, self.response(self.device(), {
                "access_token": self.access_token(), "expires_in": 300, "refresh_token": "old-refresh",
            }), args)
            self.now += 400
            code, _, error = self.run_helper(files, self.response(
                {"error": "invalid_grant"}, self.device(),
                {"access_token": self.access_token(), "expires_in": 300},
            ), args)
            self.assertEqual(code, 0, error)
            self.assertIsNone(json.loads(next(Path(directory).glob("*.json")).read_text())["refresh_token"])

    def test_offline_refresh_stops_after_the_session_limit(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            files = {"DATALAB_CLIENT_SECRET_VALUE": "test-secret", "DATALAB_TOKEN_CACHE_DIR": directory}
            args = ["--client-secret-env", "DATALAB_CLIENT_SECRET_VALUE"]
            started = self.now
            code, _, error = self.run_helper(files, self.response(self.device(), {
                "access_token": self.access_token(), "expires_in": 300, "refresh_token": "offline-refresh",
            }), args)
            self.assertEqual(code, 0, error)
            self.now = started + 29 * 24 * 60 * 60
            code, _, error = self.run_helper(files, self.response({
                "access_token": self.access_token(), "expires_in": 300, "refresh_token": "rotated-offline-refresh",
            }), args)
            self.assertEqual(code, 0, error)
            self.assertEqual(error, "")
            self.assertEqual(self.requests[-1][1]["grant_type"], ["refresh_token"])
            cached = json.loads(next(Path(directory).glob("*.json")).read_text())
            self.assertEqual(cached["session_expires_at"], started + 1 + 30 * 24 * 60 * 60)
            self.now = started + 31 * 24 * 60 * 60
            code, _, error = self.run_helper(files, self.response(self.device(), {
                "access_token": self.access_token(), "expires_in": 300, "refresh_token": "new-offline-refresh",
            }), args)
            self.assertEqual(code, 0, error)
            self.assertIn("TEST-CODE", error)
            self.assertTrue(self.requests[-2][0].endswith('/auth/device'))

    def test_refresh_policy_error_does_not_start_device_login_or_change_scopes(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            files = {"DATALAB_CLIENT_SECRET_VALUE": "test-secret", "DATALAB_TOKEN_CACHE_DIR": directory}
            args = ["--client-secret-env", "DATALAB_CLIENT_SECRET_VALUE"]
            self.run_helper(files, self.response(self.device(), {
                "access_token": self.access_token(), "expires_in": 300, "refresh_token": "offline-refresh",
            }), args)
            self.now += 400
            requests_before = len(self.requests)
            code, output, error = self.run_helper(files, self.response({
                "error": "invalid_request", "error_description": "Request not allowed",
            }), args)
            self.assertEqual(code, 1)
            self.assertEqual(output, "")
            self.assertIn("client policies", error)
            self.assertEqual(len(self.requests), requests_before + 1)
            self.assertEqual(self.requests[-1][1]["grant_type"], ["refresh_token"])
            self.assertNotIn("scope", self.requests[-1][1])

    def test_device_denial_expiry_and_bad_client_return_no_credentials(self):
        for responses in (
            [self.device(), {"error": "access_denied"}],
            [self.device(expires_in=3), {"error": "authorization_pending"}, {"error": "authorization_pending"}],
            [{"error": "invalid_client"}],
        ):
            with self.subTest(responses=responses), TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
                code, output, _ = self.run_helper({
                    "DATALAB_CLIENT_SECRET_VALUE": "test-secret", "DATALAB_TOKEN_CACHE_DIR": directory,
                }, self.response(*responses), ["--client-secret-env", "DATALAB_CLIENT_SECRET_VALUE"])
                self.assertNotEqual(code, 0)
                self.assertEqual(output, "")
                self.assertEqual(list(Path(directory).glob("*.json")), [])

    def test_login_caches_are_separate_and_can_be_reset(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            files = {"DATALAB_CLIENT_SECRET_VALUE": "test-secret", "DATALAB_TOKEN_CACHE_DIR": directory}
            for extra in ([], ["--issuer", "https://other.example/realm"], ["--client-id", "s-other"],
                          ["--scope", "s-joe:vclusters_vc0_demo"], ["--force-login"]):
                code, _, error = self.run_helper(files, self.response(self.device(), {
                    "access_token": self.access_token(), "expires_in": 300,
                }), ["--client-secret-env", "DATALAB_CLIENT_SECRET_VALUE", *extra])
                self.assertEqual(code, 0, error)
            self.assertEqual(len(list(Path(directory).glob("*.json"))), 4)
        self.assertEqual(len(self.requests), 10)

    def test_missing_secret_prompts_once_and_cached_token_needs_no_secret(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            files = {"DATALAB_TOKEN_CACHE_DIR": directory,
                     "KUBERNETES_EXEC_INFO": json.dumps({"spec": {"interactive": True}})}
            value = self.access_token()
            code, output, error = self.run_helper(files, self.response(self.device(), {
                "access_token": value, "expires_in": 300, "refresh_token": "test-refresh",
            }), interactive=True, prompt="prompted-secret")
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["status"]["token"], value)
            self.assertNotIn("prompted-secret", output + error)
            self.assertNotIn("prompted-secret", next(Path(directory).glob("*.json")).read_text())
            code, output, error = self.run_helper({
                **files, "KUBERNETES_EXEC_INFO": json.dumps({"spec": {"interactive": False}}),
            })
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["status"]["token"], value)
            self.assertEqual(len(self.prompts), 1)
            self.assertEqual(self.requests[0][1]["client_secret"], ["prompted-secret"])

    def test_refresh_prompts_when_the_secret_is_not_stored(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            files = {"DATALAB_TOKEN_CACHE_DIR": directory}
            code, _, error = self.run_helper(files, self.response(self.device(), {
                "access_token": self.access_token(), "expires_in": 300, "refresh_token": "test-refresh",
            }), interactive=True, prompt="prompted-secret")
            self.assertEqual(code, 0, error)
            self.now += 400
            value = self.access_token()
            code, output, error = self.run_helper(files, self.response({
                "access_token": value, "expires_in": 300,
            }), interactive=True, prompt="prompted-secret")
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["status"]["token"], value)
            self.assertEqual(len(self.prompts), 2)
            self.assertEqual(self.requests[-1][1]["grant_type"], ["refresh_token"])

    def test_noninteractive_login_does_not_prompt(self):
        for info in ({"spec": {"interactive": False}}, {"spec": {}}):
            code, output, error = self.run_helper({"KUBERNETES_EXEC_INFO": json.dumps(info)}, interactive=True)
            self.assertNotEqual(code, 0)
            self.assertEqual(output, "")
            self.assertIn("DATALAB_CLIENT_SECRET_FILE", error)
            self.assertEqual(self.prompts, [])

    def test_secret_prompt_cannot_fall_back_to_echo(self):
        from getpass import GetPassWarning
        import warnings

        def echo_warning():
            warnings.warn('Terminal control unavailable', GetPassWarning)

        code, output, _ = self.run_helper({}, interactive=True, prompt=echo_warning)
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")
        self.assertEqual(self.requests, [])

    def test_corrupt_cache_starts_device_login(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            files = {"DATALAB_CLIENT_SECRET_VALUE": "test-secret", "DATALAB_TOKEN_CACHE_DIR": directory}
            args = ["--client-secret-env", "DATALAB_CLIENT_SECRET_VALUE"]
            response = lambda: self.response(self.device(), {"access_token": self.access_token(), "expires_in": 300})
            self.run_helper(files, response(), args)
            next(Path(directory).glob("*.json")).write_text("incomplete json")
            code, _, error = self.run_helper(files, response(), args)
            self.assertEqual(code, 0, error)

    def test_empty_or_ambiguous_sources_fail_without_a_credential(self):
        with TemporaryDirectory(prefix="test-vcluster-credential-sources-") as directory:
            empty = Path(directory) / "empty"
            empty.write_text("")
            for sources in (
                {"DATALAB_ACCESS_TOKEN_FILE": str(empty)},
                {"DATALAB_CLIENT_SECRET_FILE": str(empty)},
                {"DATALAB_ACCESS_TOKEN_FILE": str(empty), "DATALAB_CLIENT_SECRET_FILE": str(empty)},
            ):
                code, output, _ = self.run_helper(sources)
                self.assertNotEqual(code, 0)
                self.assertEqual(output, "")


class VclusterDelegatedTokenTests(unittest.TestCase):
    @staticmethod
    def access_token(exp=1893456000):
        payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
        return "header." + payload + ".signature"

    def run_helper(self, files, args=()):
        module = runpy.run_path(str(ROOT / "scripts/vcluster-credentials.py"))
        output, error = StringIO(), StringIO()
        argv = ["credentials.py", "--token-only", *args]
        with patch.object(sys, "argv", argv), patch.object(module["os"], "environ", files), \
                redirect_stdout(output), redirect_stderr(error):
            try:
                code = module["main"]()
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), error.getvalue()

    def test_profile_requires_a_separate_credential_source(self):
        code, output, error = self.run_helper({})
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")
        self.assertIn("DATALAB_ACCESS_TOKEN_FILE", error)

    def test_delegated_token_sources_need_no_client_credentials(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            token = Path(directory) / "access-token"
            value = self.access_token()
            token.write_text(value + "\n")
            for files, args in (
                ({"DATALAB_ACCESS_TOKEN_FILE": str(token)}, []),
                ({}, ["--access-token-file", str(token)]),
                ({"DATALAB_ACCESS_TOKEN_FILE": str(token),
                  "DATALAB_CLIENT_SECRET_FILE": "/unused/client-secret"}, []),
            ):
                with self.subTest(files=files, args=args):
                    code, output, error = self.run_helper(files, args)
                    self.assertEqual(code, 0, error)
                    self.assertEqual(json.loads(output)["status"], {
                        "token": value, "expirationTimestamp": "2030-01-01T00:00:00Z",
                    })

    def test_client_secret_cannot_replace_a_caller_token(self):
        code, output, _ = self.run_helper({"DATALAB_CLIENT_SECRET_FILE": "/unused/client-secret"})
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")

    def test_empty_or_missing_token_files_fail_without_a_credential(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            empty = Path(directory) / "empty"
            empty.write_text("")
            for token in (empty, Path(directory) / "missing"):
                with self.subTest(token=token.name):
                    code, output, _ = self.run_helper({"DATALAB_ACCESS_TOKEN_FILE": str(token)})
                    self.assertNotEqual(code, 0)
                    self.assertEqual(output, "")

    def test_invalid_token_expiry_fails_without_a_credential(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            token = Path(directory) / "access-token"
            for value in ("invalid", "header.e30.signature", self.access_token("invalid")):
                with self.subTest(value=value):
                    token.write_text(value)
                    code, output, _ = self.run_helper({"DATALAB_ACCESS_TOKEN_FILE": str(token)})
                    self.assertNotEqual(code, 0)
                    self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
