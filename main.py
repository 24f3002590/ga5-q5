from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, List
import re

app = FastAPI()


class Step(BaseModel):
    step_number: int
    tool: str
    args: Dict[str, Any]
    tokens_used: int


class RequestModel(BaseModel):
    budget_tokens: int
    steps: List[Step]


def normalize_string(s: str) -> str:
    # Collapse whitespace and trim
    return re.sub(r"\s+", " ", s).strip()


def canonicalize(obj):
    """
    Canonicalize args:
    - Remove any field named trace_id
    - Ignore key order
    - Normalize whitespace in strings
    """
    if isinstance(obj, dict):
        items = []
        for k in sorted(obj.keys()):
            if k == "trace_id":
                continue
            items.append((k, canonicalize(obj[k])))
        return tuple(items)

    if isinstance(obj, list):
        return tuple(canonicalize(x) for x in obj)

    if isinstance(obj, str):
        return normalize_string(obj)

    return obj


def same_call(a: Step, b: Step):
    return (
        a.tool == b.tool
        and canonicalize(a.args) == canonicalize(b.args)
    )


@app.post("/")
@app.post("/guard")
@app.post("/run-control")
def guard(req: RequestModel):

    total = sum(s.tokens_used for s in req.steps)

    # Budget rule
    if total >= req.budget_tokens:
        return {
            "decision": "halt",
            "reason": f"Cumulative tokens_used ({total}) has reached the budget ({req.budget_tokens})."
        }

    steps = req.steps

    # -------- 3 identical consecutive calls --------
    run = 1
    for i in range(1, len(steps)):
        if same_call(steps[i], steps[i - 1]):
            run += 1
            if run >= 3:
                return {
                    "decision": "halt",
                    "reason": "Detected three identical consecutive tool calls."
                }
        else:
            run = 1

    # -------- Trailing ABABAB cycle --------
    if len(steps) >= 6:
        tail = steps[-6:]

        A = tail[0]
        B = tail[1]

        cycle = True
        for i in range(6):
            expected = A if i % 2 == 0 else B
            if not same_call(tail[i], expected):
                cycle = False
                break

        # Must actually alternate
        if cycle and not same_call(A, B):
            return {
                "decision": "halt",
                "reason": "Detected repeating two-step cycle."
            }

    return {
        "decision": "continue",
        "reason": "Within budget and no looping pattern detected."
    }
