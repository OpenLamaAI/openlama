"""Tool: calculator – safe math expression evaluation."""

import ast
import math
import operator

from openlama.tools.registry import register_tool

_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_SAFE_FUNCS = {
    "abs": abs, "round": round, "min": min, "max": max,
    "sqrt": math.sqrt, "log": math.log, "log10": math.log10, "log2": math.log2,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "ceil": math.ceil, "floor": math.floor,
    "pi": math.pi, "e": math.e,
}


def _safe_eval(expr: str):
    tree = ast.parse(expr, mode="eval")
    return _eval_node(tree.body)


def _eval_node(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Disallowed constant: {node.value}")
    if isinstance(node, ast.BinOp):
        op = _SAFE_OPS.get(type(node.op))
        if not op:
            raise ValueError(f"Disallowed operator: {type(node.op).__name__}")
        return op(_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _SAFE_OPS.get(type(node.op))
        if not op:
            raise ValueError(f"Disallowed operator: {type(node.op).__name__}")
        return op(_eval_node(node.operand))
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in _SAFE_FUNCS:
            fn = _SAFE_FUNCS[node.func.id]
            if callable(fn):
                args = [_eval_node(a) for a in node.args]
                return fn(*args)
        raise ValueError(f"Disallowed function: {ast.dump(node.func)}")
    if isinstance(node, ast.Name):
        if node.id in _SAFE_FUNCS:
            val = _SAFE_FUNCS[node.id]
            if not callable(val):
                return val
        raise ValueError(f"Disallowed name: {node.id}")
    raise ValueError(f"Disallowed expression: {type(node).__name__}")


async def _execute(args: dict) -> str:
    expression = args.get("expression", "").strip()
    if not expression:
        return "Please provide a math expression."
    try:
        result = _safe_eval(expression)
        return f"{expression} = {result}"
    except Exception as e:
        return f"Calculation error: {e}"


register_tool(
    name="calculator",
    description="Evaluate math expressions precisely. Supports arithmetic, exponentiation, trigonometric functions, logarithms, etc.",
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Math expression to evaluate (e.g., '2**10', 'sqrt(144)', 'log(100)')",
            },
        },
        "required": ["expression"],
    },
    execute=_execute,
)
