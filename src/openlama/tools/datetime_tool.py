"""Tool: get_datetime – returns current date/time."""

from datetime import datetime, timezone, timedelta

from openlama.tools.registry import register_tool

KST = timezone(timedelta(hours=9))


async def _execute(args: dict) -> str:
    now = datetime.now(KST)
    return (
        f"Current time (KST): {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Day: {now.strftime('%A')}\n"
        f"ISO: {now.isoformat()}\n"
        f"Unix: {int(now.timestamp())}"
    )


register_tool(
    name="get_datetime",
    description="Returns the current date and time (KST, Korea Standard Time)",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    execute=_execute,
)
