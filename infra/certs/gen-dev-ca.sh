#!/usr/bin/env bash
# Development CA and MQTT broker certificate for TLS on 8883 (NFR-03).
#
#   infra/certs/gen-dev-ca.sh [extra SAN ...]     e.g. 192.168.1.20 pids-laptop.local
#
# Writes infra/certs/out/ (git-ignored). The CA is created once and reused; the broker
# certificate is reissued on every run, so adding a LAN IP is just a re-run. Edge nodes
# get only ca.crt — they verify the broker; the CA key never leaves this machine.
set -euo pipefail

out="$(cd "$(dirname "$0")" && pwd)/out"
mkdir -p "$out"
chmod 700 "$out"

if [[ ! -f "$out/ca.key" ]]; then
  openssl ecparam -name prime256v1 -genkey -noout -out "$out/ca.key"
  openssl req -x509 -new -key "$out/ca.key" -sha256 -days 1095 \
    -subj "/O=PIDS/CN=PIDS development CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -out "$out/ca.crt"
  echo "created development CA"
fi

sans="DNS:mqtt,DNS:localhost,IP:127.0.0.1"
for extra in "$@"; do
  if [[ "$extra" =~ ^[0-9.]+$ || "$extra" == *:* ]]; then sans+=",IP:$extra"; else sans+=",DNS:$extra"; fi
done

openssl ecparam -name prime256v1 -genkey -noout -out "$out/broker.key"
openssl req -new -key "$out/broker.key" -subj "/O=PIDS/CN=mqtt" -out "$out/broker.csr"
openssl x509 -req -in "$out/broker.csr" -CA "$out/ca.crt" -CAkey "$out/ca.key" -CAcreateserial \
  -days 397 -sha256 -out "$out/broker.crt" \
  -extfile <(printf 'subjectAltName=%s\nextendedKeyUsage=serverAuth\nkeyUsage=critical,digitalSignature\n' "$sans")
rm -f "$out/broker.csr"
chmod 600 "$out"/*.key
echo "broker certificate for: $sans"
openssl verify -CAfile "$out/ca.crt" "$out/broker.crt"
