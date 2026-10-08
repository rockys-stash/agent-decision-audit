"""A small, safe expression language for recorded calculations and policy rules.

Calculations and rules are recorded as an expression plus its named operands, so an auditor
(or the replay engine, or the violation detector) can recompute them without running agent
code. Only arithmetic, comparisons, boolean logic, conditional expressions, membership tests
and a fixed set of pure functions are allowed; anything else is rejected at parse time.
"""

from __future__ import annotations

import ast
import functools
import operator
from collections.abc import Callable, Mapping
from typing import Any

_BIN: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_CMP: dict[type[ast.cmpop], Callable[[Any, Any], Any]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}
FUNCTIONS: dict[str, Callable[..., Any]] = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "sum": sum,
    "len": len,
}
MAX_LENGTH = 400


class ExpressionError(ValueError):
    pass


@functools.lru_cache(maxsize=4096)
def parse(source: str) -> ast.Expression:
    if len(source) > MAX_LENGTH:
        raise ExpressionError("expression too long")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as e:
        raise ExpressionError(f"invalid expression: {e.msg}") from e
    for node in ast.walk(tree):
        if isinstance(
            node,
            ast.Expression
            | ast.BinOp
            | ast.UnaryOp
            | ast.BoolOp
            | ast.Compare
            | ast.IfExp
            | ast.Name
            | ast.Constant
            | ast.Load
            | ast.List
            | ast.Tuple
            | ast.And
            | ast.Or
            | ast.Not
            | ast.USub
            | ast.UAdd,
        ):
            continue
        if isinstance(node, ast.operator) and type(node) in _BIN:
            continue
        if isinstance(node, ast.cmpop) and type(node) in _CMP:
            continue
        if isinstance(node, ast.Call):
            if (
                not isinstance(node.func, ast.Name)
                or node.func.id not in FUNCTIONS
                or node.keywords
            ):
                raise ExpressionError("only min, max, abs, round, sum and len may be called")
            continue
        raise ExpressionError(f"{type(node).__name__} is not allowed in expressions")
    return tree


def names(source: str) -> set[str]:
    tree = parse(source)
    called = {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - called


def evaluate(source: str, operands: Mapping[str, Any]) -> Any:
    tree = parse(source)
    missing = names(source) - set(operands)
    if missing:
        raise ExpressionError(f"missing operands: {', '.join(sorted(missing))}")
    return _eval(tree.body, operands)


def _eval(node: ast.expr, env: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, ast.List | ast.Tuple):
        return [_eval(e, env) for e in node.elts]
    if isinstance(node, ast.BinOp):
        return _BIN[type(node.op)](_eval(node.left, env), _eval(node.right, env))
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, env)
        if isinstance(node.op, ast.Not):
            return not v
        return -v if isinstance(node.op, ast.USub) else +v
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_eval(v, env) for v in node.values)
        return any(_eval(v, env) for v in node.values)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op, comp in zip(node.ops, node.comparators, strict=True):
            right = _eval(comp, env)
            if not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(node.body, env) if _eval(node.test, env) else _eval(node.orelse, env)
    if isinstance(node, ast.Call):
        assert isinstance(node.func, ast.Name)
        return FUNCTIONS[node.func.id](*[_eval(a, env) for a in node.args])
    raise ExpressionError(f"{type(node).__name__} is not allowed")  # pragma: no cover
