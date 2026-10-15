# ADR-0006: Edge node runs natively for the laptop demo, containerised on Linux

- **Status:** Accepted
- **Date:** 2026-10-16
- **Requirements:** NFR-07, AIL-14

## Context

The Raspberry Pi 5, thermal array and tag reader are not yet in hand. The demo runs on
an Apple-Silicon laptop (ARM64, same ISA as the Pi 5). Docker Desktop on macOS cannot
pass USB cameras or serial devices into containers.

## Decision

The edge node is a normal Python package run natively on the demo laptop, and shipped
as a `linux/arm64` image for the Pi. Every sensor sits behind a driver interface with a
real and a simulated implementation; thermal and RFID use simulated sources until the
hardware arrives, selected by configuration.

## Consequences

The demo uses the real camera and real GPS module. Swapping in real thermal/RFID
hardware is a configuration change, not a code change upstream of the driver.
