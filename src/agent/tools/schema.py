"""Provider-agnostic tool schema definitions.

Each tool defines its schema once; providers translate to their
specific format (OpenAI function calling, Anthropic tool_use, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolParameter:
    """A single parameter for a tool."""

    name: str
    type: str  # "string", "integer", "boolean", "number", "array", "object"
    description: str
    required: bool = True
    enum: list[str] | None = None
    default: Any = None
    items: dict[str, Any] | None = None  # For array types


@dataclass
class ToolSchema:
    """Schema describing a tool's interface."""

    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)

    def to_json_schema(self) -> dict[str, Any]:
        """Convert to JSON Schema format (used by all providers)."""
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param in self.parameters:
            prop: dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.items:
                prop["items"] = param.items
            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema

    def validate_and_coerce(self, arguments: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Validate ``arguments`` against this schema and coerce simple types.

        Reuses the same ``required`` / ``type`` / ``default`` declarations that
        are advertised to the LLM, so the runtime enforces what the model was
        told. Returns ``(coerced_args, errors)``:

        * missing required params -> an error message (arg is left absent),
        * omitted optional params with a default -> the default is injected,
        * ``integer``/``number``/``boolean`` values given as strings are coerced,
        * unknown params are passed through untouched (providers may add extras).

        This never raises; callers decide what to do with ``errors``.
        """
        by_name = {p.name: p for p in self.parameters}
        coerced = dict(arguments)
        errors: list[str] = []

        for param in self.parameters:
            present = param.name in coerced and coerced[param.name] is not None
            if not present:
                if param.required:
                    errors.append(f"missing required argument '{param.name}' ({param.type})")
                elif param.default is not None:
                    coerced[param.name] = param.default
                continue

            value = coerced[param.name]
            try:
                coerced[param.name] = _coerce(value, param.type)
            except (ValueError, TypeError):
                errors.append(
                    f"argument '{param.name}' should be {param.type}, got {type(value).__name__}"
                )

            if param.enum and coerced[param.name] not in param.enum:
                errors.append(
                    f"argument '{param.name}' must be one of {param.enum}, got {coerced[param.name]!r}"
                )

        return coerced, errors


def _coerce(value: Any, type_name: str) -> Any:
    """Best-effort coercion of scalar values to the declared JSON type."""
    if type_name == "integer":
        if isinstance(value, bool):
            raise ValueError("bool is not an integer")
        if isinstance(value, int):
            return value
        return int(str(value).strip())
    if type_name == "number":
        if isinstance(value, bool):
            raise ValueError("bool is not a number")
        if isinstance(value, (int, float)):
            return value
        return float(str(value).strip())
    if type_name == "boolean":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("true", "1", "yes", "on"):
            return True
        if s in ("false", "0", "no", "off"):
            return False
        raise ValueError(f"cannot coerce {value!r} to boolean")
    # string / array / object: pass through
    return value
