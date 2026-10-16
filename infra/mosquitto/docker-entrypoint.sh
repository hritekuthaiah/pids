#!/bin/sh
# Builds the Mosquitto password file from environment variables at start-up so
# no credential (hashed or not) is ever committed to the repository.
#
#   MQTT_USERS="pids-server:secret1 edge-01:secret2"
set -eu

conf_dir=/mosquitto/config
passwd_file="$conf_dir/passwd"

: > "$passwd_file"
chmod 0700 "$passwd_file"

for entry in ${MQTT_USERS:?MQTT_USERS must list user:password pairs}; do
  user=${entry%%:*}
  pass=${entry#*:}
  mosquitto_passwd -b "$passwd_file" "$user" "$pass"
done

chown mosquitto:mosquitto "$passwd_file"
mkdir -p "$conf_dir/conf.d"

# TLS listener on 8883 when certificates exist (infra/certs/gen-dev-ca.sh, mounted at
# /mosquitto/certs). The key is copied so the mosquitto user can read it whatever
# the host file's owner; without certificates only the local 1883 listener runs.
rm -f "$conf_dir/conf.d/tls.conf"
if [ -f /mosquitto/certs/broker.crt ] && [ -f /mosquitto/certs/broker.key ]; then
  install -d -o mosquitto -g mosquitto -m 0700 "$conf_dir/certs"
  install -o mosquitto -g mosquitto -m 0644 /mosquitto/certs/ca.crt /mosquitto/certs/broker.crt "$conf_dir/certs/"
  install -o mosquitto -g mosquitto -m 0600 /mosquitto/certs/broker.key "$conf_dir/certs/"
  cat > "$conf_dir/conf.d/tls.conf" <<CONF
listener 8883 0.0.0.0
cafile $conf_dir/certs/ca.crt
certfile $conf_dir/certs/broker.crt
keyfile $conf_dir/certs/broker.key
tls_version tlsv1.2
CONF
  echo "TLS listener enabled on 8883"
fi

exec /usr/sbin/mosquitto -c "$conf_dir/mosquitto.conf"
