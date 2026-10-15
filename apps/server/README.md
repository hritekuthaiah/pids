# pids-server

One image, three processes: `pids-api` (REST + WebSocket gateway), `pids-decision`
(consumes MQTT telemetry, runs the decision core, persists and publishes) and
`pids-worker` (notification dispatch and background jobs). `pids-admin` seeds sites and users.
