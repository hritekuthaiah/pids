"""Helpers shared by server integration tests."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "integration-test-password"


async def login(client: AsyncClient, email: str) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    body: dict[str, str] = r.json()
    return body


def bearer(tokens: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}
