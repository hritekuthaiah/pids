# ADR-0012: Passive BLE badges — rolling identifiers, evidence-based linking

- **Status:** Accepted
- **Date:** 2026-10-16
- **Requirements:** AIL-09, PLT-02, NFR-02, NFR-03; refines ADR-0005

## Context

Whitelisting must be autonomous: authorised people should never tap, scan or check
in (an RFID tap at a gate is a repetitive manual step, so the demo won't rely on it).
There is no budget for dedicated badges before the demo, but every team member
carries an Android phone. Bluetooth Low Energy lets a phone advertise passively and
lets the edge laptop listen. Two risks come with that:

1. **Replay:** a fixed identifier can be recorded once and rebroadcast by an intruder.
2. **Misattribution:** a scanner hears a badge somewhere within ~10 m, through walls,
   with no position. "Give it to the nearest person" whitelists an intruder walking
   beside an authorised person, or one in view while the badge holder is next door.
   That is a missed intruder, the worst failure (NFR-02).

## Decision

- **Rolling identifiers.** A badge advertises manufacturer-specific data with company
  id `0xFFFF` (reserved by the Bluetooth SIG for testing): `"PD" ‖ version ‖ id`. The
  `id` is the first 8 bytes of `HMAC-SHA256(badge_secret, "pids-ble" ‖ window)`, with
  30-second windows. `badge_secret = HMAC-SHA256(site_key, tag_id)`.
  - The scanner needs only the site key (`PIDS_BADGE_KEY`, in `.env`) and the tag
    registry, and it accepts one window of clock skew.
  - A captured id expires in at most ~90 s.
  - A phone gets its own secret from an authenticated, audited endpoint
    (`GET /guards/me/badge`), and only its own.
  - Fixed "static" ids exist for bench testing with off-the-shelf advertiser apps.
    They are accepted only with an explicit `allow_static` flag.
- **Linking by physics, not proximity.** Received signal strength follows log-distance
  path loss, so as the badge holder moves, their badge's RSSI rises and falls with
  *their* distance to the scanner. Over a 10 s window, the engine computes the Spearman
  rank correlation between the RSSI and each in-range person track's `-log10(distance)`.
  - A badge is linked only when the correlation is at least 0.6 and beats every other
    person in range by at least 0.3.
  - A person standing still gives no evidence and counts as uncorrelated, not as absent.
  - Two people walking side by side are ambiguous, so **nobody** is linked until their
    paths diverge (recall first).
  - An earned link holds (hysteresis) until someone else clearly fits better, the badge
    falls silent for 6 s, or the person leaves.
  - Two badges claiming one person: neither is trusted.
  - Links follow a person across a tracker re-acquisition (stitching).
- **Badges lower threat, never zero it.** They feed the existing `authorized_tag`
  fusion term. A CRITICAL breach still requires geometric evidence (ADR-0009).
- **Readers have a kind.** An `rfid` read happens at the reader, so the nearest person
  is still the one tapping. A `ble` reader uses the linker above.
- **Scanner:** `bleak` (CoreBluetooth on macOS, BlueZ on a Pi). Raw adverts are
  averaged into at most one `TagRead` per badge every 0.4 s, which smooths multipath
  spikes.

## Alternatives considered

- *Nearest track within reader range:* simple, and wrong in exactly the demo case
  (badged teammate and intruder entering together).
- *RSSI trilateration with several scanners:* needs hardware we don't have, and indoor
  RSSI is too noisy to localise to the ~1 m that separates two people.
- *UWB tags:* precise ranging, but a purchase. ESP32 BLE badges running this same
  protocol are the upgrade path.

## Consequences

- The demo whitelists a teammate passively within a few seconds of them walking in,
  and visibly refuses to whitelist anyone while an intruder walks alongside.
- The phone side needs the guard app to advertise (Android foreground service).
- Replay within the ~90 s validity window, in the same room, is still possible.
  Pairing a badge with its camera track's motion makes this hard: a replayer would have
  to move exactly as the original holder did.
- The scanner needs macOS Bluetooth permission for the app that runs it.
