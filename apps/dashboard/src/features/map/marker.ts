import type { ThreatAssessment } from "@pids/api-client";
import { Marker } from "maplibre-gl";

import { entityLabel } from "../../lib/format";

export interface EntityMarker {
  marker: Marker;
  root: HTMLDivElement;
  arrow: HTMLDivElement;
  label: HTMLDivElement;
}

/**
 * Entities are DOM markers rather than GL symbols: CSS gives the pulse rings,
 * glow and reticle for free, and the console never needs a glyph server — so it
 * keeps working on an air-gapped network.
 */
export function createEntityMarker(a: ThreatAssessment, onClick: () => void): EntityMarker {
  const root = document.createElement("div");
  root.className = "entity";
  root.setAttribute("role", "button");
  root.setAttribute("aria-label", `${a.entity_class} ${entityLabel(a.entity_id)}`);
  root.innerHTML = `<span class="entity-ring"></span><span class="entity-reticle"></span>`;
  const arrow = document.createElement("div");
  arrow.className = "entity-arrow";
  const dot = document.createElement("div");
  dot.className = "entity-dot";
  const label = document.createElement("div");
  label.className = "entity-label";
  root.append(arrow, dot, label);
  root.addEventListener("click", (e) => {
    e.stopPropagation();
    onClick();
  });
  const marker = new Marker({ element: root, anchor: "center" });
  return { marker, root, arrow, label };
}

export function updateEntityMarker(
  m: EntityMarker,
  a: ThreatAssessment,
  heading: number | null,
  selected: boolean,
): void {
  m.root.dataset["level"] = a.level;
  m.root.dataset["tagged"] = String(a.authorized);
  m.root.classList.toggle("is-selected", selected);
  m.arrow.style.display = heading === null ? "none" : "block";
  if (heading !== null) m.arrow.style.transform = `rotate(${heading.toFixed(0)}deg)`;
  const cls = a.authorized ? `${a.entity_class} · tagged` : a.entity_class;
  m.label.textContent = `${cls.toUpperCase()}  ${a.score}`;
}
