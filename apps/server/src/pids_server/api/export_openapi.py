"""Write the OpenAPI document (plus WebSocket message schemas) for client codegen.

    uv run python -m pids_server.api.export_openapi packages/api-client/openapi.json

The WebSocket stream is not part of REST, so its message envelopes are added as
named component schemas; the TypeScript clients get exact types for both.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel

from pids_server.api.main import create_app
from pids_server.schemas import (
    AlertMessage,
    AlertsSnapshotMessage,
    LiveMessage,
    SiteChangedMessage,
)
from pids_server.settings import Settings

WS_MESSAGES: dict[str, type[BaseModel]] = {
    "LiveMessage": LiveMessage,
    "AlertMessage": AlertMessage,
    "AlertsSnapshotMessage": AlertsSnapshotMessage,
    "SiteChangedMessage": SiteChangedMessage,
}


def build() -> dict[str, Any]:
    settings = Settings(
        postgres_password="x",  # noqa: S106 — never connects; schema generation only
        redis_password="x",  # noqa: S106
        mqtt_server_password="x",  # noqa: S106
        jwt_secret="x",  # noqa: S106
    )
    app = create_app(settings)
    spec = get_openapi(title=app.title, version=app.version, routes=app.routes)
    components = spec.setdefault("components", {}).setdefault("schemas", {})
    for name, model in WS_MESSAGES.items():
        schema = model.model_json_schema(
            ref_template="#/components/schemas/{model}", mode="serialization"
        )
        for def_name, definition in schema.pop("$defs", {}).items():
            components.setdefault(def_name, definition)
        components[name] = schema
    return spec


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    text = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
