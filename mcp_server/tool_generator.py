"""Generate MCP tool definitions from FormGraph data.

The form graph's `mapped_key` fields are the single source of truth for
parameter names. The tool spec (from LLM) provides tool_name and description.
The input_schema is built from graph_data fields directly.
"""

import re


def generate_tool_definition(form) -> dict | None:
    """Generate an MCP tool definition from an approved FormGraph.

    Builds input_schema from graph_data fields using mapped_key as parameter
    names. Falls back to label-derived keys for old graphs without mapped_key.

    Args:
        form: FormGraph ORM object with mcp_tool_spec and graph_data

    Returns:
        dict with name, description, input_schema, form_id — or None if no data
    """
    graph = form.graph_data
    spec = form.mcp_tool_spec

    if not graph:
        return None

    all_steps = _get_all_steps(graph)
    if not all_steps:
        return None

    properties = {}
    required = []

    for step in all_steps:
        step_id = (step.get("id") or "").lower()
        step_title = (step.get("title") or "").lower()
        if step_id == "consent" or "einwilligung" in step_id or "einwilligung" in step_title:
            continue
        # Skip special step types (auth gate, info page, final page)
        if step.get("step_type") in ("auth_gate", "info_page", "final_page"):
            continue
        for section in step.get("sections", []):
            for field in section.get("fields", []):
                label = field.get("label", "")
                if not label:
                    continue

                # mapped_key is the single source of truth
                key = field.get("mapped_key") or _field_key(label)
                if key in properties:
                    # Deduplicate — append step number
                    key = f"{key}_{step.get('id', step.get('step', ''))}"

                ftype = field.get("type", "text")
                if ftype == "file":
                    prop = {
                        "type": "string",
                        "description": f"{label} (base64-kodierter Dateiinhalt)",
                        "format": "binary",
                    }
                else:
                    prop = {"type": "string", "description": label}
                    if field.get("options") and isinstance(field["options"], list):
                        prop["enum"] = field["options"]
                    if field.get("format"):
                        prop["description"] += f" (Format: {field['format']})"
                properties[key] = prop
                if field.get("required"):
                    required.append(key)

    if not properties:
        return None

    tool_name = (spec or {}).get("tool_name", _slug_from_title(form.title))
    description = (spec or {}).get("description", f"Formular ausfuellen: {form.title}")

    return {
        "name": f"fill_form__{tool_name}",
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
        "form_id": str(form.id),
    }


def _get_all_steps(graph_data: dict) -> list[dict]:
    """Get all steps from a graph, handling both linear and branching forms."""
    if not graph_data:
        return []

    exploration_type = graph_data.get("exploration_type", "linear")

    if exploration_type == "branching":
        common = graph_data.get("common_steps", [])
        branches = graph_data.get("branch_paths", [])
        # Include common steps + first branch for the tool definition
        if branches:
            return common + branches[0].get("steps", [])
        return common

    return graph_data.get("steps", [])


def _slug_from_title(title: str) -> str:
    """Generate a snake_case slug from a German title."""
    slug = title.lower()
    for old, new in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")]:
        slug = slug.replace(old, new)
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")[:60]
    return slug


def _field_key(label: str) -> str:
    """Convert a German field label to a snake_case key (fallback for old graphs)."""
    key = label.lower()
    key = key.replace("*", "").strip()
    for old, new in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")]:
        key = key.replace(old, new)
    key = re.sub(r"[^a-z0-9]+", "_", key)
    return key.strip("_")
