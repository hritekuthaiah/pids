# ADR-0005: Cooperative-tag whitelisting instead of facial recognition

- **Status:** Accepted
- **Date:** 2026-10-16
- **Requirements:** AIL-12, PLT-02, NFR-04

## Context

The system must distinguish authorised personnel/assets from intruders. Facial
recognition is the obvious option and the one examiners will ask about.

## Decision

Identity comes only from cooperative tags (RFID/BLE, or a GPS-reporting device such as
the guard app). No biometric data is collected, stored or matched.

## Consequences

- Removes consent, bias and false-match liabilities and aligns with the data-minimisation
  principle of India's DPDP Act.
- Works at night and at distance, where faces are unusable anyway.
- An authorised person who forgets their tag is treated as unidentified — the system
  fails toward raising an alarm, which matches the recall-first principle.
- Tags can be cloned, lent or dropped, so a tag **reduces** threat but never zeroes it,
  and GPS tags are checked for spoofing (AIL-15).
