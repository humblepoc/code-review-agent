"""Schema enforcement + loop dispatch behavior."""
import pytest

from agent.core.loop import _execute_tool, _cap, MAX_TOOL_ERROR_CHARS
from agent.tools.base import Tool, ToolRegistry
from agent.tools.schema import ToolParameter, ToolSchema


class _EchoTool(Tool):
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="t",
            description="d",
            parameters=[
                ToolParameter(name="project_id", type="string", description="p"),
                ToolParameter(name="mr_iid", type="integer", description="i"),
                ToolParameter(name="flag", type="boolean", description="f",
                              required=False, default=False),
            ],
        )

    async def execute(self, **kwargs):
        return f"pid={kwargs['project_id']!r} iid={kwargs['mr_iid']!r}({type(kwargs['mr_iid']).__name__}) flag={kwargs['flag']!r}"


def _reg():
    r = ToolRegistry()
    r.register(_EchoTool())
    return r


def test_validate_missing_required():
    coerced, errors = _EchoTool().schema().validate_and_coerce({"project_id": "x/y"})
    assert any("mr_iid" in e for e in errors)


def test_validate_coerces_int_and_injects_default():
    coerced, errors = _EchoTool().schema().validate_and_coerce(
        {"project_id": "x/y", "mr_iid": "503"}
    )
    assert not errors
    assert coerced["mr_iid"] == 503
    assert coerced["flag"] is False  # default injected


def test_bool_coercion():
    coerced, errors = _EchoTool().schema().validate_and_coerce(
        {"project_id": "x", "mr_iid": 1, "flag": "true"}
    )
    assert not errors and coerced["flag"] is True


async def test_loop_rejects_missing_arg_cleanly():
    res = await _execute_tool(_reg(), "t", {"project_id": "x/y"}, "id1")
    assert res.is_error
    assert "missing required argument 'mr_iid'" in res.content


async def test_loop_coerces_and_executes():
    res = await _execute_tool(_reg(), "t", {"project_id": "x/y", "mr_iid": "503"}, "id2")
    assert not res.is_error
    assert "iid=503(int)" in res.content
    assert "flag=False" in res.content


async def test_unknown_tool():
    res = await _execute_tool(_reg(), "nope", {}, "id3")
    assert res.is_error and "Unknown tool" in res.content


def test_cap_truncates():
    long = "x" * (MAX_TOOL_ERROR_CHARS + 100)
    out = _cap(long)
    assert len(out) < len(long) and "truncated" in out
