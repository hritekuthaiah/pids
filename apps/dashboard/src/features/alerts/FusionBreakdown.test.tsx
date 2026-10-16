import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { assessment } from "../../test/fixtures";
import { FusionBreakdown } from "./FusionBreakdown";

describe("FusionBreakdown", () => {
  it("lists contributing channels by magnitude with signed log-odds", () => {
    const a = assessment();
    render(<FusionBreakdown contributions={a.contributions} probability={0.82} />);
    const items = within(screen.getByRole("list", { name: "Evidence contributions" })).getAllByRole(
      "listitem",
    );
    expect(items.map((li) => li.textContent)).toEqual([
      "Inside warning band+1.54",
      "Vision · person+1.33",
      "Behavioural anomaly−0.10",
    ]);
    expect(screen.getByText("0.82")).toBeInTheDocument();
  });

  it("reports unavailable channels as neutral, not as negative evidence", () => {
    const a = assessment();
    render(<FusionBreakdown contributions={a.contributions} probability={0.5} />);
    expect(
      screen.getByText(/Unavailable \(neutral\): Thermal · heat confirmed/),
    ).toBeInTheDocument();
  });

  it("omits channels that contributed nothing", () => {
    const a = assessment();
    render(<FusionBreakdown contributions={a.contributions} probability={0.5} />);
    expect(screen.queryByText("Authorised tag")).not.toBeInTheDocument();
  });
});
