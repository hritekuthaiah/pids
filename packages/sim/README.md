# pids-sim

Seeded, labelled perimeter scenarios — intruders on foot and in vehicles, fence
probers, loiterers, tagged patrols, gate staff with RFID badges, a quick-reaction
vehicle, animals, public-road traffic, asset theft and a spoofed GPS tag — rendered
through realistic sensor models (camera field of view, range-dependent detection and
localisation error, class confusion, ID switches, ghost tracks, thermal coverage,
GPS noise and dropouts, gate RFID reads).

Output uses the exact `pids_core.contracts` messages the real edge node produces, so
the decision engine cannot tell simulation from hardware. Every rendered track and tag
maps back to the agent that produced it, which is what the evaluation scores against.
