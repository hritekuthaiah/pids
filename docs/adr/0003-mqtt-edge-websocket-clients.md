# ADR-0003: MQTT for edge telemetry, WebSockets for clients

- **Status:** Accepted
- **Date:** 2026-10-16
- **Requirements:** PLT-04, NFR-01, NFR-03, NFR-05, NFR-07

## Context

Edge nodes are battery-powered devices on WiFi/4G links that drop. Clients (dashboard,
guard app) need sub-second push. The kickoff specified WebSockets for realtime.

## Decision

- **Edge → platform:** MQTT (Eclipse Mosquitto) with per-node credentials, topic ACLs,
  QoS 1 and client-side persistence so telemetry survives link loss; TLS on 8883 off
  localhost. Brokers can bridge (Pi → cloud) natively.
- **Platform → clients:** WebSockets from the API, fed through Redis pub/sub so any
  number of API replicas can serve clients.
- **Internal jobs:** Redis Streams with consumer groups (durable, acknowledged) for
  notifications and agent work.

## Consequences

The IoT-standard protocol where devices are involved and a browser-native one where
humans are. Two transports to operate, but each is the right tool for its link.
