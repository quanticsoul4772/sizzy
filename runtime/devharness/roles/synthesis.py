"""Structured synthesis for the research (spec body) and director (task decomposition) roles
(spec rev 0.3.23). Each asks the model to compose JSON, then parses + strictly validates it; any
malformed / non-JSON output yields None so the caller falls back to its prior templated behaviour.
The fallback is the old behaviour, so a bad model response can never produce a worse spec/plan than
before — synthesis only ever upgrades the result.
"""

import json

# The BUILD task classes a decomposition may target (maintenance is not a planned BUILD class).
BUILD_CLASSES = frozenset({"new_project_scaffold", "feature", "bugfix", "refactor", "dependency_bump"})


def extract_json(text):
    """The outermost JSON value (object or array) in text, or None. Tolerates code fences / prose."""
    if not isinstance(text, str):
        return None
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        return None
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    if end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def parse_spec_body(text):
    """Validate a synthesized spec body. scope + verification_plan are non-empty strings;
    non_goals / interfaces / success_criteria are lists of strings (success_criteria non-empty).
    Returns the normalized dict or None (→ caller templates the body)."""
    obj = extract_json(text)
    if not isinstance(obj, dict):
        return None
    scope, vplan = obj.get("scope"), obj.get("verification_plan")
    if not (isinstance(scope, str) and scope.strip() and isinstance(vplan, str) and vplan.strip()):
        return None
    out = {"scope": scope.strip(), "verification_plan": vplan.strip()}
    for key in ("non_goals", "interfaces", "success_criteria"):
        val = obj.get(key, [])
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            return None
        out[key] = [x.strip() for x in val if x.strip()]
    if not out["success_criteria"]:
        return None  # a spec with no success criteria is no improvement over the template
    return out


def parse_task_list(text, valid_classes=BUILD_CLASSES):
    """Validate a decomposed task list. Each task: task_class in valid_classes, non-empty
    description, scope_boundary list[str], dependencies list[str]. Any malformed task → None for
    the whole list (fail closed to the caller's single-task fallback)."""
    obj = extract_json(text)
    if isinstance(obj, dict):
        obj = obj.get("tasks")
    if not isinstance(obj, list) or not obj:
        return None
    tasks = []
    for t in obj:
        if not isinstance(t, dict):
            return None
        tc, desc = t.get("task_class"), t.get("description")
        scope, deps = t.get("scope_boundary", []), t.get("dependencies", [])
        if tc not in valid_classes or not (isinstance(desc, str) and desc.strip()):
            return None
        if not (isinstance(scope, list) and all(isinstance(x, str) for x in scope)):
            return None
        if not (isinstance(deps, list) and all(isinstance(x, str) for x in deps)):
            return None
        tasks.append({"task_class": tc, "description": desc.strip(),
                      "scope_boundary": list(scope), "dependencies": list(deps)})
    return tasks or None


WORK_ITEM_KINDS = frozenset({"feature", "bugfix", "refactor", "test_gap", "dependency"})


def parse_work_items(text, valid_kinds=WORK_ITEM_KINDS):
    """Validate a discovered work-item list (issue-discovery). Each item: non-empty title + description,
    kind in valid_kinds, scope_hint list[str]; rationale optional. Any malformed item → None for the whole
    list (fail closed to 'no candidates', never a partial/garbage list)."""
    obj = extract_json(text)
    if isinstance(obj, dict):
        obj = obj.get("work_items") or obj.get("candidates")
    if not isinstance(obj, list) or not obj:
        return None
    items = []
    for it in obj:
        if not isinstance(it, dict):
            return None
        title, desc, kind = it.get("title"), it.get("description"), it.get("kind")
        scope, rationale = it.get("scope_hint", []), it.get("rationale", "")
        if not (isinstance(title, str) and title.strip() and isinstance(desc, str) and desc.strip()):
            return None
        if kind not in valid_kinds:
            return None
        if not (isinstance(scope, list) and all(isinstance(x, str) for x in scope)):
            return None
        if not isinstance(rationale, str):
            rationale = ""
        items.append({"title": title.strip(), "description": desc.strip(),
                      "rationale": rationale.strip(), "kind": kind, "scope_hint": list(scope)})
    return items or None


def synthesis_prompt(operator_idea, assumptions, repo_summary=None) -> str:
    """Prompt the model to compose a spec body from the operator idea + interview assumptions.

    repo_summary (Gap C): when the spec targets an EXISTING repository, a structural summary of that
    repo (from a read-only explore pass) is fed in so the model grounds scope/interfaces/success_criteria
    in the codebase's actual shape and proposes a feature that fits it, rather than from the seed alone.
    None keeps the greenfield prompt unchanged.
    """
    lines = "\n".join(f"- {a}" for a in assumptions) or "- (none)"
    repo_section = ""
    if repo_summary:
        repo_section = (
            "\nThe specification targets an EXISTING repository — propose a feature that FITS this codebase, "
            "and ground scope/interfaces/success_criteria in its actual structure below (read-only "
            f"structural scan; structure only, not file contents):\n{repo_summary}\n"
        )
    return (
        "Compose a software specification body for the following operator request, using the "
        "interview assumptions as the source of intent. Return ONLY a JSON object with keys: "
        "scope (string), non_goals (array of strings), interfaces (array of strings), "
        "success_criteria (array of strings), verification_plan (string). No prose outside the JSON.\n\n"
        f"Operator request:\n{operator_idea}\n{repo_section}\nInterview assumptions:\n{lines}\n"
    )


def decompose_prompt(spec) -> str:
    """Prompt the model to decompose a signed spec into an ordered BUILD task list.

    Complexity-aware (rev 0.3.23 follow-up): a simple greenfield stays one new_project_scaffold,
    but a greenfield whose success criteria describe many independently-testable behaviours
    decomposes into a minimal scaffold + ordered per-behaviour feature tasks. The success criteria
    are fed in so the model has the granular behaviours to split on (each task verifiable against
    one criterion), instead of collapsing the whole build into a single all-or-nothing task.

    Inherent-error folding (rev 0.3.64): the split rule alone over-decomposed — an error/edge-case
    criterion whose behaviour the implementation of another task NECESSARILY produces (e.g. the
    validation error a parser already raises on malformed input) was planned as its own task, which
    reached the developer as an empty test-only diff the spec_claim axis correctly rejects: a wasted
    multi-minute worker run per occurrence (the csvlite t2/t5 redundant-task pattern). Such
    behaviours are folded into the task that introduces the code; a separate task is planned only
    for behaviour requiring its OWN new code (a prior drive's exception→exit-code mapping was real
    code — the fold rule must not swallow that back into under-decomposition).
    """
    assumptions = "\n".join(f"- {a}" for a in spec.get("assumptions", [])) or "- (none)"
    criteria = "\n".join(f"- {c}" for c in spec.get("success_criteria", [])) or "- (none)"
    non_goals = "\n".join(f"- {g}" for g in spec.get("non_goals", [])) or "- (none)"
    return (
        "Decompose this signed specification into an ordered list of BUILD tasks. Return ONLY a JSON "
        "array; each element is an object with keys: task_class (one of "
        f"{sorted(BUILD_CLASSES)}), description (string), scope_boundary (array of path globs the task "
        "may touch), dependencies (array of earlier task descriptions it depends on, or []). "
        "Decompose to the point where each task is INDEPENDENTLY VERIFIABLE against the success "
        "criteria below, and no further. A simple greenfield is one new_project_scaffold task; but a "
        "greenfield whose success criteria describe MANY independently-testable behaviours should be a "
        "minimal new_project_scaffold (the package skeleton + entry-point + the single simplest "
        "behaviour, end-to-end runnable) followed by ordered feature tasks — one per independently-"
        "verifiable behaviour — each declaring the scaffold (and any prerequisite task) in its "
        "dependencies. Do not bundle many independently-verifiable behaviours into one task. "
        "EXCEPTION — inherent error/edge cases: an error or edge-case behaviour that the "
        "implementation of another task necessarily produces (e.g. the validation error a parser "
        "already raises on malformed input, or the empty-input case a loop already handles) is NOT "
        "a separate task — fold it into the description and verification of the task that "
        "introduces that code. Plan a separate task for an error/edge behaviour ONLY when it "
        "requires its own new code beyond what its prerequisite tasks build (e.g. mapping raised "
        "exceptions to specific exit codes and user-facing messages IS its own code). Stay "
        "WITHIN the signed scope: plan NO task for anything listed under Non-goals (explicit "
        "exclusions) — they are out of bounds, not work to do. No prose outside the JSON.\n\n"
        f"Problem:\n{spec.get('problem', '')}\n\nScope:\n{spec.get('scope', '')}\n\n"
        f"Non-goals (do NOT plan tasks for these):\n{non_goals}\n\n"
        f"Success criteria:\n{criteria}\n\nAssumptions:\n{assumptions}\n"
    )
