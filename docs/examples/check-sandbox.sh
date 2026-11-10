#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

if [[ $# != 3 || ( $1 != write && $1 != read ) ]]; then
  printf 'Usage: bash %s write|read REST_PORT GRPC_PORT\n' "$0" >&2
  exit 2
fi
for tool in curl grpcurl python3; do
  command -v "${tool}" >/dev/null || { printf 'Install %s first.\n' "${tool}" >&2; exit 1; }
done
mode=$1
rest_port=$2
grpc_port=$3
for port in "${rest_port}" "${grpc_port}"; do
  [[ ${port} =~ ^[0-9]{1,5}$ ]] && ((10#${port} > 0 && 10#${port} <= 65535)) || {
    printf 'Ports must be numbers from 1 to 65535.\n' >&2
    exit 2
  }
done
proto_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../tests/vcluster" && pwd)"
file_url="http://127.0.0.1:${rest_port}/v1/files/manual-check.txt"
marker='sandbox check from local'
curl_args=(--fail --silent --show-error --max-time 15 --noproxy '*')

curl "${curl_args[@]}" "http://127.0.0.1:${rest_port}/v1/health" >/dev/null
printf 'PASS sandboxd health\n'
if [[ ${mode} == write ]]; then
  curl "${curl_args[@]}" --request PUT --header 'Content-Type: application/octet-stream' \
    --data-binary "${marker}" "${file_url}" >/dev/null
fi
[[ "$(curl "${curl_args[@]}" "${file_url}")" == "${marker}" ]] || {
  printf 'The REST file content does not match.\n' >&2
  exit 1
}
printf 'PASS REST file content\n'

grpcurl -plaintext -max-time 15 -import-path "${proto_directory}" -proto process.proto \
  -d '{"config":{"command":["cat","/workspace/manual-check.txt"]}}' \
  "127.0.0.1:${grpc_port}" process.v1.ProcessService/Execute |
  python3 -c '
import base64
import json
import sys
result = json.load(sys.stdin)
if result.get("exitCode", 0) != 0 or base64.b64decode(result.get("stdout", "")) != b"sandbox check from local":
    sys.exit("The sandboxd command failed or returned different file content.")
print("PASS gRPC command: cat /workspace/manual-check.txt")
'
