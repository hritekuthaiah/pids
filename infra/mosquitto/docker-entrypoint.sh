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

exec /usr/sbin/mosquitto -c "$conf_dir/mosquitto.conf"
