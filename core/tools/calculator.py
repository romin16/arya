"""Small arithmetic expression evaluator. It never calls Python eval()."""
from __future__ import annotations

import ast
import math
import operator
from typing import Callable


_BINARY: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def calculate(expression: str) -> float | int:
    """Evaluate numeric literals and basic arithmetic with a bounded exponent."""
    if not expression or len(expression) > 256:
        raise ValueError("Enter a shorter arithmetic expression.")
    try:
        tree = ast.parse(expression, mode="eval")
        result = _evaluate(tree.body)
    except (SyntaxError, ZeroDivisionError, OverflowError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("Exponents"):
            raise
        raise ValueError("I couldn't calculate that expression safely.") from None
    if not math.isfinite(float(result)) or abs(result) > 1e100:
        raise ValueError("That result is outside the supported range.")
    if isinstance(result, float) and result.is_integer():
        return int(result)
    return result


def _evaluate(node: ast.AST) -> float | int:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        if abs(node.value) > 1e100:
            raise ValueError("That number is outside the supported range.")
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("Exponents are limited to 100.")
        return _BINARY[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_evaluate(node.operand))
    raise ValueError("Unsupported expression element.")
