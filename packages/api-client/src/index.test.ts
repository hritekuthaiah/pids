import { describe, expect, it } from "vitest";

import { levelRank, secondsUntilExpiry } from "./index";

function jwt(payload: object): string {
  const b64 = (o: object) =>
    btoa(JSON.stringify(o)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64(payload)}.signature`;
}

describe("secondsUntilExpiry", () => {
  const now = Date.UTC(2026, 9, 27, 4, 30, 0);

  it("reads exp from the token payload", () => {
    expect(secondsUntilExpiry(jwt({ exp: now / 1000 + 600 }), now)).toBe(600);
  });

  it("is zero for expired, malformed or exp-less tokens", () => {
    expect(secondsUntilExpiry(jwt({ exp: now / 1000 - 5 }), now)).toBe(0);
    expect(secondsUntilExpiry("not-a-jwt", now)).toBe(0);
    expect(secondsUntilExpiry(jwt({ sub: "x" }), now)).toBe(0);
  });
});

describe("levelRank", () => {
  it("orders threat levels", () => {
    expect(
      ["critical", "nominal", "warning", "elevated"].sort((a, b) => levelRank(a) - levelRank(b)),
    ).toEqual(["nominal", "elevated", "warning", "critical"]);
  });
});
