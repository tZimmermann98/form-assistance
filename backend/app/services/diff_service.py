"""Graph diff engine — compares two FormGraph versions and classifies changes.

Severity levels:
- none: identical
- cosmetic: label text slightly changed, help text updated
- structural: new field added, type changed, options changed
- breaking: required field removed, step removed, URL broken
"""

from dataclasses import dataclass, field, asdict


@dataclass
class FieldChange:
    step: int
    step_title: str
    section: str
    field_label: str
    change_type: str  # added | removed | type_changed | label_changed | required_changed | options_changed
    old_value: str | None = None
    new_value: str | None = None


@dataclass
class StepChange:
    change_type: str  # added | removed
    step: int
    title: str


@dataclass
class DiffResult:
    severity: str  # none | cosmetic | structural | breaking
    step_changes: list[StepChange] = field(default_factory=list)
    field_changes: list[FieldChange] = field(default_factory=list)
    summary_de: str = ""

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "step_changes": [asdict(sc) for sc in self.step_changes],
            "field_changes": [asdict(fc) for fc in self.field_changes],
            "summary_de": self.summary_de,
        }


def _levenshtein(a: str, b: str) -> int:
    """Simple Levenshtein distance."""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[len(b)]


def _normalize(label: str) -> str:
    """Normalize label for comparison."""
    import re
    return re.sub(r"\s+", " ", label.replace("*", "")).strip().lower()


def _extract_fields_flat(graph: dict) -> list[dict]:
    """Extract a flat list of {step, step_title, section, label, type, required, options} from a graph."""
    fields = []
    for step in graph.get("steps", []):
        step_num = step.get("step", 0)
        step_title = step.get("title", "")
        step_id = step.get("id", "")
        if step_id == "consent":
            continue
        for section in step.get("sections", []):
            sec_name = section.get("section", "")
            for f in section.get("fields", []):
                label_norm = _normalize(f.get("label", ""))
                # Use step_id + label to create unique composite key
                composite_key = f"{step_id}::{label_norm}"
                fields.append({
                    "step": step_num,
                    "step_title": step_title,
                    "step_id": step_id,
                    "section": sec_name,
                    "label": f.get("label", ""),
                    "label_norm": label_norm,
                    "composite_key": composite_key,
                    "type": f.get("type", "text"),
                    "required": f.get("required", False),
                    "options": f.get("options"),
                })
    return fields


def diff_form_graphs(old_graph: dict, new_graph: dict) -> DiffResult:
    """Compare two form graphs and classify changes."""
    if not old_graph or not new_graph:
        return DiffResult(severity="none", summary_de="Kein Vergleich moeglich.")

    step_changes = []
    field_changes = []

    # ── Step-level comparison ──
    old_steps = {s.get("id", s.get("step")): s for s in old_graph.get("steps", [])}
    new_steps = {s.get("id", s.get("step")): s for s in new_graph.get("steps", [])}

    old_ids = set(old_steps.keys())
    new_ids = set(new_steps.keys())

    for sid in new_ids - old_ids:
        s = new_steps[sid]
        if s.get("id") != "consent":
            step_changes.append(StepChange("added", s.get("step", 0), s.get("title", "")))

    for sid in old_ids - new_ids:
        s = old_steps[sid]
        if s.get("id") != "consent":
            step_changes.append(StepChange("removed", s.get("step", 0), s.get("title", "")))

    # ── Field-level comparison ──
    old_fields = _extract_fields_flat(old_graph)
    new_fields = _extract_fields_flat(new_graph)

    # Use composite key (step_id::label_norm) to handle duplicate labels across steps
    old_by_key = {f["composite_key"]: f for f in old_fields}
    new_by_key = {f["composite_key"]: f for f in new_fields}

    old_keys = set(old_by_key.keys())
    new_keys = set(new_by_key.keys())

    # New fields
    for key in new_keys - old_keys:
        # Check for fuzzy match within same step (cosmetic rename)
        nf = new_by_key[key]
        best_match = None
        best_dist = 999
        for old_key in old_keys - new_keys:
            of = old_by_key[old_key]
            # Only fuzzy match within the same step
            if of["step_id"] != nf["step_id"]:
                continue
            dist = _levenshtein(nf["label_norm"], of["label_norm"])
            if dist < best_dist:
                best_dist = dist
                best_match = old_key

        if best_match and best_dist <= 3:
            of = old_by_key[best_match]
            field_changes.append(FieldChange(
                step=nf["step"], step_title=nf["step_title"], section=nf["section"],
                field_label=nf["label"], change_type="label_changed",
                old_value=of["label"], new_value=nf["label"],
            ))
        else:
            field_changes.append(FieldChange(
                step=nf["step"], step_title=nf["step_title"], section=nf["section"],
                field_label=nf["label"], change_type="added",
                new_value=f"{nf['type']}, {'Pflicht' if nf['required'] else 'optional'}",
            ))

    # Removed fields
    for key in old_keys - new_keys:
        # Skip if it was matched as a rename above
        of = old_by_key[key]
        already_matched = any(
            fc.change_type == "label_changed" and _normalize(fc.old_value or "") == of["label_norm"]
            and fc.step == of["step"]
            for fc in field_changes
        )
        if already_matched:
            continue

        field_changes.append(FieldChange(
            step=of["step"], step_title=of["step_title"], section=of["section"],
            field_label=of["label"], change_type="removed",
            old_value=f"{of['type']}, {'Pflicht' if of['required'] else 'optional'}",
        ))

    # Changed fields (same composite key, different attributes)
    for key in old_keys & new_keys:
        of = old_by_key[key]
        nf = new_by_key[key]

        if of["type"] != nf["type"]:
            field_changes.append(FieldChange(
                step=nf["step"], step_title=nf["step_title"], section=nf["section"],
                field_label=nf["label"], change_type="type_changed",
                old_value=of["type"], new_value=nf["type"],
            ))

        if of["required"] != nf["required"]:
            field_changes.append(FieldChange(
                step=nf["step"], step_title=nf["step_title"], section=nf["section"],
                field_label=nf["label"], change_type="required_changed",
                old_value=str(of["required"]), new_value=str(nf["required"]),
            ))

        if of.get("options") != nf.get("options") and (of.get("options") or nf.get("options")):
            field_changes.append(FieldChange(
                step=nf["step"], step_title=nf["step_title"], section=nf["section"],
                field_label=nf["label"], change_type="options_changed",
                old_value=str(of.get("options")), new_value=str(nf.get("options")),
            ))

    # ── Classify severity ──
    severity = "none"
    if field_changes or step_changes:
        severity = "cosmetic"

    # Structural changes
    structural_types = {"added", "type_changed", "required_changed", "options_changed"}
    if any(fc.change_type in structural_types for fc in field_changes):
        severity = "structural"
    if any(sc.change_type == "added" for sc in step_changes):
        severity = "structural"

    # Breaking changes
    if any(fc.change_type == "removed" and "Pflicht" in (fc.old_value or "") for fc in field_changes):
        severity = "breaking"
    if any(sc.change_type == "removed" for sc in step_changes):
        severity = "breaking"

    # ── Build German summary ──
    parts = []
    added_count = sum(1 for fc in field_changes if fc.change_type == "added")
    removed_count = sum(1 for fc in field_changes if fc.change_type == "removed")
    renamed_count = sum(1 for fc in field_changes if fc.change_type == "label_changed")
    type_changed_count = sum(1 for fc in field_changes if fc.change_type == "type_changed")
    req_changed_count = sum(1 for fc in field_changes if fc.change_type == "required_changed")
    steps_added = sum(1 for sc in step_changes if sc.change_type == "added")
    steps_removed = sum(1 for sc in step_changes if sc.change_type == "removed")

    if steps_added:
        parts.append(f"{steps_added} neue(r) Schritt(e)")
    if steps_removed:
        parts.append(f"{steps_removed} Schritt(e) entfernt")
    if added_count:
        parts.append(f"{added_count} neue(s) Feld(er)")
    if removed_count:
        parts.append(f"{removed_count} Feld(er) entfernt")
    if renamed_count:
        parts.append(f"{renamed_count} Feld(er) umbenannt")
    if type_changed_count:
        parts.append(f"{type_changed_count} Typ(en) geaendert")
    if req_changed_count:
        parts.append(f"{req_changed_count} Pflichtfeld-Aenderung(en)")

    summary = ", ".join(parts) if parts else "Keine Aenderungen."

    return DiffResult(
        severity=severity,
        step_changes=step_changes,
        field_changes=field_changes,
        summary_de=summary,
    )
