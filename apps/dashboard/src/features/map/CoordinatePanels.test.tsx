import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CoordinateImport, CornerTable, LocationSection } from "./CoordinatePanels";
import type { Draft } from "./editor";

const ORIGIN = { lat: 13.262, lon: 77.42 };

function location(over: Partial<Parameters<typeof LocationSection>[0]> = {}) {
  const props = {
    origin: ORIGIN,
    moved: false,
    carry: true,
    placing: false,
    onOrigin: vi.fn(),
    onCarry: vi.fn(),
    onPlace: vi.fn(),
    ...over,
  };
  render(<LocationSection {...props} />);
  return props;
}

/** jsdom has neither a secure-context flag nor a geolocation; the panel needs both. */
function stubGeolocation(
  getCurrentPosition: (ok: PositionCallback, fail: PositionErrorCallback) => void,
  secure = true,
) {
  Object.defineProperty(window, "isSecureContext", { value: secure, configurable: true });
  Object.defineProperty(navigator, "geolocation", {
    value: { getCurrentPosition },
    configurable: true,
  });
}

afterEach(() => {
  Reflect.deleteProperty(navigator, "geolocation");
});

describe("site location", () => {
  it("shows the site's origin in both boxes", () => {
    location();
    expect(screen.getByLabelText("Site latitude")).toHaveValue("13.2620000");
    expect(screen.getByLabelText("Site longitude")).toHaveValue("77.4200000");
  });

  it("applies typed coordinates when you leave the box", async () => {
    const user = userEvent.setup();
    const p = location();
    const lat = screen.getByLabelText("Site latitude");
    await user.clear(lat);
    await user.type(lat, "13.1");
    expect(p.onOrigin).not.toHaveBeenCalled(); // nothing is half-applied mid-typing
    await user.tab();
    expect(p.onOrigin).toHaveBeenCalledExactlyOnceWith(13.1, 77.42);
  });

  it("applies on Enter", async () => {
    const user = userEvent.setup();
    const p = location();
    const lon = screen.getByLabelText("Site longitude");
    await user.clear(lon);
    await user.type(lon, "77.5{Enter}");
    expect(p.onOrigin).toHaveBeenCalledExactlyOnceWith(13.262, 77.5);
  });

  it("takes a pasted lat, lon pair into both", async () => {
    const user = userEvent.setup();
    const p = location();
    const lat = screen.getByLabelText("Site latitude");
    await user.clear(lat);
    await user.click(lat);
    await user.paste("12.9716, 77.5946");
    await user.tab();
    expect(p.onOrigin).toHaveBeenCalledExactlyOnceWith(12.9716, 77.5946);
  });

  it("flags a value that is not a coordinate and applies nothing", async () => {
    const user = userEvent.setup();
    const p = location();
    const lat = screen.getByLabelText("Site latitude");
    await user.clear(lat);
    await user.type(lat, "north{Enter}");
    expect(lat).toHaveAttribute("aria-invalid", "true");
    expect(p.onOrigin).not.toHaveBeenCalled();
    await user.clear(lat);
    await user.type(lat, "13.3");
    expect(lat).toHaveAttribute("aria-invalid", "false");
  });

  it("uses this device's position", async () => {
    stubGeolocation((ok) => {
      ok({ coords: { latitude: 12.97, longitude: 77.59, accuracy: 8 } } as GeolocationPosition);
    });
    const user = userEvent.setup();
    const p = location();
    await user.click(screen.getByRole("button", { name: "Use my location" }));
    expect(p.onOrigin).toHaveBeenCalledExactlyOnceWith(12.97, 77.59);
    expect(screen.getByText(/accurate to ±8 m/)).toBeInTheDocument();
  });

  it("says when a fix is too rough for a room", async () => {
    stubGeolocation((ok) => {
      ok({ coords: { latitude: 12.97, longitude: 77.59, accuracy: 120 } } as GeolocationPosition);
    });
    const user = userEvent.setup();
    location();
    await user.click(screen.getByRole("button", { name: "Use my location" }));
    expect(screen.getByText(/rough for a room/)).toBeInTheDocument();
  });

  it("explains a refused permission instead of failing silently", async () => {
    stubGeolocation((_, fail) => {
      fail({
        code: 1,
        PERMISSION_DENIED: 1,
        TIMEOUT: 3,
        POSITION_UNAVAILABLE: 2,
      } as GeolocationPositionError);
    });
    const user = userEvent.setup();
    const p = location();
    await user.click(screen.getByRole("button", { name: "Use my location" }));
    expect(screen.getByText(/Location is blocked/)).toBeInTheDocument();
    expect(p.onOrigin).not.toHaveBeenCalled();
  });

  it("says why it cannot locate on an insecure page", async () => {
    stubGeolocation(vi.fn(), false);
    const user = userEvent.setup();
    const p = location();
    await user.click(screen.getByRole("button", { name: "Use my location" }));
    expect(screen.getByText(/https:\/\/ pages or localhost/)).toBeInTheDocument();
    expect(p.onOrigin).not.toHaveBeenCalled();
  });

  it("locks the carry option once the site has moved", () => {
    location({ moved: true });
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.getByText(/moved · unsaved/)).toBeInTheDocument();
  });

  it("toggles carry and picking on the map", async () => {
    const user = userEvent.setup();
    const p = location();
    await user.click(screen.getByRole("checkbox"));
    expect(p.onCarry).toHaveBeenCalledWith(false);
    await user.click(screen.getByRole("button", { name: "Pick on map" }));
    expect(p.onPlace).toHaveBeenCalledOnce();
  });
});

const ROOM: Draft = {
  id: "room",
  name: "Room",
  kind: "critical",
  ring: [
    [77.42, 13.262],
    [77.4201, 13.262],
    [77.4201, 13.2621],
    [77.42, 13.2621],
  ],
};

describe("corner table", () => {
  const table = (draft: Draft = ROOM) => {
    const handlers = { onCorner: vi.fn(), onAdd: vi.fn(), onRemove: vi.fn() };
    render(<CornerTable draft={draft} {...handlers} />);
    return handlers;
  };

  it("lists every corner as latitude and longitude", () => {
    table();
    expect(screen.getByLabelText("Latitude of corner 3")).toHaveValue("13.2621000");
    expect(screen.getByLabelText("Longitude of corner 3")).toHaveValue("77.4201000");
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
  });

  it("moves a corner to typed coordinates", async () => {
    const user = userEvent.setup();
    const h = table();
    const lon = screen.getByLabelText("Longitude of corner 2");
    await user.clear(lon);
    await user.type(lon, "77.4205{Enter}");
    expect(h.onCorner).toHaveBeenCalledExactlyOnceWith("room", 1, 13.262, 77.4205);
  });

  it("adds and removes corners", async () => {
    const user = userEvent.setup();
    const h = table();
    await user.click(screen.getByRole("button", { name: "Add a corner after corner 2" }));
    expect(h.onAdd).toHaveBeenCalledWith("room", 1);
    await user.click(screen.getByRole("button", { name: "Remove corner 4" }));
    expect(h.onRemove).toHaveBeenCalledWith("room", 3);
  });

  it("will not remove the third-from-last corner", () => {
    table({ ...ROOM, ring: ROOM.ring.slice(0, 3) });
    for (const b of screen.getAllByRole("button", { name: /Remove corner/ })) {
      expect(b).toBeDisabled();
    }
  });
});

describe("add a zone from coordinates", () => {
  it("adds the pasted corners as the chosen kind", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn();
    render(<CoordinateImport onAdd={onAdd} />);
    await user.click(screen.getByText("Add a zone from coordinates"));
    await user.click(screen.getByLabelText(/Zone corners/));
    await user.paste("13.262, 77.42\n13.262, 77.4201\n13.2621, 77.4201");
    await user.selectOptions(screen.getByLabelText("Kind of the new zone"), "warning");
    await user.click(screen.getByRole("button", { name: "Add zone" }));
    expect(onAdd).toHaveBeenCalledExactlyOnceWith("warning", [
      [77.42, 13.262],
      [77.4201, 13.262],
      [77.4201, 13.2621],
    ]);
    expect(screen.getByLabelText(/Zone corners/)).toHaveValue(""); // ready for the next one
  });

  it("names the line it could not read and adds nothing", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn();
    render(<CoordinateImport onAdd={onAdd} />);
    await user.click(screen.getByText("Add a zone from coordinates"));
    await user.click(screen.getByLabelText(/Zone corners/));
    await user.paste("13.262, 77.42\nnope\n13.2, 77.4");
    await user.click(screen.getByRole("button", { name: "Add zone" }));
    expect(screen.getByText(/Line 2/)).toBeInTheDocument();
    expect(onAdd).not.toHaveBeenCalled();
  });
});
