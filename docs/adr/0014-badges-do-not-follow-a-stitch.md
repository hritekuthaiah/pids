# ADR-0014: BLE badges do not follow a tracker re-acquisition

- **Status:** Accepted
- **Date:** 2026-11-20
- **Requirements:** AIL-09, NFR-02; supersedes one rule of ADR-0012

## Context

When a camera loses a person for a moment, the tracker gives them a new ID. The decision
engine *stitches* the new track to a track on the same node that ended up to 4 s earlier,
within 8 m of where that track was heading, so the person keeps their class belief and
identity. ADR-0012 extended this to BLE badges: "links follow a person across a tracker
re-acquisition".

The stitch matches on motion alone. Outdoors, 8 m is a narrow gate. In the 8 × 6 m demo
room it covers the whole floor, and a review against the demo script found three ways
the badge reaches the wrong person:

1. **Walk-out handover.** The holder leaves view through the door. An intruder entering
   there 1.5 s later is the only candidate, so the stitch hands them the badge. The
   linker's hysteresis then holds it, and the intruder walked into the secure core with
   no alert at all.
2. **Batch order.** A new track listed before a live track in the same batch saw that
   live track as "lost" (last updated one frame ago). An intruder appearing beside the
   holder took the badge, and the real holder went CRITICAL.
3. **No ambiguity check.** When two people were lost together, the nearest predicted
   position won outright: a coin flip with two people half a metre apart.

Each of these whitelists an intruder on motion evidence that cannot tell two people
apart, which breaks "if in doubt, nobody is whitelisted" (ADR-0005, ADR-0012).

## Decision

**A BLE badge never follows a stitch.** The new track starts unbadged. The badge stays
with the old, unseen track until that track expires or the linker finds a clearly better
fit, and the linker re-earns the link from RSSI-vs-motion evidence as usual.

**One-shot identity (an RFID gate read, a GPS tag association) follows a stitch only
when it is unambiguous.** Exactly one lost track may lie within the gate; a lost track
that has already passed its identity on is not a candidate again. RFID and GPS keep the
carry because a gate read cannot be re-earned once the person has walked past.

**A track still present in the current batch is never a stitch candidate.** It is being
tracked, so the new track is someone else.

Class belief and track age still carry from the nearest candidate, even when ambiguous.
Both are about *a person*, not *which person*, and an older track age makes the recall
floor apply sooner, never later.

## Consequences

- An intruder can no longer inherit a badge by entering as its holder leaves, by
  appearing beside the holder, or by being re-acquired together with them.
- After a re-acquisition the badge holder is briefly unbadged: until the old track
  expires (6 s) and the linker has fresh evidence (a few seconds of walking). They may
  show ELEVATED or raise a WARNING in that gap. That is the recall-first trade, and the
  same thing already happens when two people walk side by side.
- The 8 m stitch gate is unchanged. At room scale it now errs safe: more pairs of lost
  tracks count as ambiguous, so less identity is carried.
- Not addressed: an ID switch *inside* the edge tracker (one ID jumping between two
  bodies in a crossing) moves the link with the ID. The linker's evidence corrects it
  over its 10 s window. Rehearse crossings and watch for it.
- Regression tests: `test_badges.py` (the three room scenarios above) and
  `test_engine.py` (RFID carried only when unambiguous).
