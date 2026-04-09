"""Structured LLM prompts for the form explorer.

All prompts instruct the model to respond in valid JSON only.
"""

SYSTEM_PROMPT = """\
You are a form analysis assistant for German municipal web forms.
You receive raw extracted form field data, page context, and a screenshot from a Playwright browser.
Your task is to interpret the form structure and produce a clean, structured JSON representation.

Rules:
- All output must be valid JSON. No markdown, no code fences, no explanations.
- Field labels should be in German exactly as they appear on the form.
- Date format for Muenster forms is always DD.MM.YYYY.
- Never include element IDs — they are session-scoped and change every visit.
- Detect group-required patterns (Pflichtgruppe) where at least one field in a group must be filled.
- Detect conditional logic where selecting an option reveals/hides fields.
- BundID / eID / Servicekonto login options are NEVER automatable. If you see them, note them in the step description but do NOT include them as required fields. We always use the anonymous/guest path.
- Focus on the form fields that a citizen needs to fill out — not login buttons or navigation elements.\
"""

# ── Step interpretation prompt ────────────────────────────────────────────

STEP_INTERPRETATION_PROMPT = """\
Analyze this form step and return a JSON object describing it.

## Raw extracted fields
{fields_json}

## Page context
Title: {page_title}
Step indicator: {step_text}
Section headings: {headings}

## Conditional logic test results
{conditional_logic_json}

## Auth gate info
{auth_gate_info}

## Instructions
Return JSON matching this exact structure:
{{
  "title": "Step title in German",
  "id": "snake_case_step_id",
  "description": "One-line description of what this step is about",
  "sections": [
    {{
      "section": "Section name from heading or logical grouping",
      "group_rule": null or "at_least_one_required",
      "fields": [
        {{
          "label": "Exact label text from the form",
          "mapped_key": "unique_snake_case_key",
          "type": "text | email | select | checkbox | radio | date | textarea | tel",
          "required": true or false,
          "format": "DD.MM.YYYY if date field, otherwise omit",
          "options": ["option1", "option2"] or null,
          "help": "Help text if present, otherwise omit",
          "conditional_logic": {{
            "option_value": {{
              "shows_fields": ["field labels that appear"],
              "hides_fields": ["field labels that disappear"],
              "shows_text": "text that appears"
            }}
          }} or null
        }}
      ]
    }}
  ]
}}

## Few-shot example (Vollmacht Step 2: Vollmachtgebende Person)

Input fields:
[{{"label": "Anrede", "type": "select", "required": true, "options": ["Herr", "Frau", "Divers"]}},
 {{"label": "Vorname", "type": "text", "required": true}},
 {{"label": "Nachname", "type": "text", "required": true}},
 {{"label": "Geburtsdatum", "type": "text", "required": true}},
 {{"label": "Strasse und Hausnummer", "type": "text", "required": true}},
 {{"label": "Postleitzahl", "type": "text", "required": true}},
 {{"label": "Ort", "type": "text", "required": true}},
 {{"label": "Telefonnummer", "type": "text", "required": false}},
 {{"label": "E-Mail-Adresse", "type": "email", "required": false}}]

Expected output:
{{
  "title": "Vollmachtgebende Person",
  "id": "vollmachtgebende_person",
  "description": "Daten der Person, die die Vollmacht erteilt (Ausweisinhaber/in)",
  "sections": [
    {{
      "section": "Persoenliche Daten",
      "group_rule": null,
      "fields": [
        {{"label": "Anrede", "mapped_key": "anrede", "type": "select", "required": true, "options": ["Herr", "Frau", "Divers"]}},
        {{"label": "Vorname", "mapped_key": "vorname", "type": "text", "required": true}},
        {{"label": "Nachname", "mapped_key": "nachname", "type": "text", "required": true}},
        {{"label": "Geburtsdatum", "mapped_key": "geburtsdatum", "type": "date", "required": true, "format": "DD.MM.YYYY"}}
      ]
    }},
    {{
      "section": "Adresse",
      "group_rule": null,
      "fields": [
        {{"label": "Strasse und Hausnummer", "mapped_key": "strasse_hausnummer", "type": "text", "required": true}},
        {{"label": "Postleitzahl", "mapped_key": "postleitzahl", "type": "text", "required": true}},
        {{"label": "Ort", "mapped_key": "adresse_ort", "type": "text", "required": true}}
      ]
    }},
    {{
      "section": "Kontakt",
      "group_rule": "at_least_one_required",
      "fields": [
        {{"label": "Telefonnummer", "mapped_key": "telefonnummer", "type": "text", "required": false, "help": "Mindestens Telefonnummer oder E-Mail-Adresse angeben"}},
        {{"label": "E-Mail-Adresse", "mapped_key": "email_adresse", "type": "email", "required": false, "help": "Mindestens Telefonnummer oder E-Mail-Adresse angeben"}}
      ]
    }}
  ]
}}

Important:
- Every field MUST have a "mapped_key": a unique, lowercase, snake_case identifier for this field across the ENTIRE form (not just this step).
- mapped_key rules:
  - Derive from the German label, replacing umlauts (ae, oe, ue, ss).
  - If a label appears more than once in the form (e.g., "Ort" in address vs birth sections), disambiguate by prefixing with section context: "adresse_ort" vs "geburtsort".
  - If two different steps have fields with the same label (e.g., "Vorname" for applicant vs "Vorname" for representative), prefix with the step/role context: "antragsteller_vorname" vs "vertreter_vorname".
  - Keys must be unique — no two fields in the entire form may share the same mapped_key.
- Group fields into sections based on headings visible on the page or logical grouping.
- If a text input clearly represents a date (label mentions Datum/Geburtsdatum), set type to "date" and format to "DD.MM.YYYY".
- If you see a pattern like "mindestens eins" or optional fields that logically form a group, set group_rule to "at_least_one_required".
- Use the screenshot to verify your interpretation matches what's visible on screen.
- Strip any asterisk (*) from labels before including them.
- If conditional logic test results are provided, include them in the field's conditional_logic property using the exact structure shown above.
- CRITICAL for conditional_logic: The key must be the TRIGGER value — the option that CAUSES new fields to appear.
  Example: if selecting "gestohlen" (stolen) reveals police report fields, write: "gestohlen": {{"shows_fields": ["Polizeimeldung"]}}
  Do NOT invert the logic. The test results show exactly which value revealed which fields — use them as-is.
- If a BundID/eID login gate was detected, note it in the step description but do NOT include login fields as required — we always use the anonymous path.\
"""


# ── MCP tool spec generation prompt ──────────────────────────────────────

MCP_SPEC_GENERATION_PROMPT = """\
Given this complete form graph, generate an MCP tool specification.

## Form Graph
{graph_json}

## Form metadata
Title: {form_title}
Source URL: {source_url}

## Instructions
Return JSON matching this exact structure:
{{
  "tool_name": "snake_case_tool_name_from_form_title",
  "description": "German description of what this form does, suitable for an AI assistant to understand when to use this tool. Include: what the form is for, what information is needed, and what the outcome is (e.g., PDF to print and sign).",
  "required_inputs": [
    {{
      "name": "snake_case_field_key",
      "type": "string",
      "description": "German description: what this field is for",
      "values": ["option1", "option2"] or null,
      "format": "DD.MM.YYYY" or null
    }}
  ],
  "optional_inputs": [
    {{
      "name": "snake_case_field_key",
      "type": "string",
      "description": "German description: what this field is for"
    }}
  ]
}}

Rules:
- tool_name should be descriptive: e.g., "vollmacht_ausweis_abholen" not just "form_1"
- Every required field from every step must appear in required_inputs
- Every optional field must appear in optional_inputs
- CRITICAL: The "name" for each input MUST be the exact "mapped_key" from the corresponding field in the form graph. Do NOT invent new keys — use the mapped_key as-is.
- For select fields with known options, include values array
- For date fields, include format "DD.MM.YYYY"
- Description should be 1-2 sentences explaining what the tool does, in German
- Do NOT include the consent checkbox — it's handled automatically
- Do NOT include BundID/eID login fields — authentication is bypassed automatically\
"""


# ── Outcome detection prompt ─────────────────────────────────────────────

OUTCOME_DETECTION_PROMPT = """\
Look at this screenshot of the final page of a German municipal form.
What happens when the form is completed? Identify the outcome type AND any action buttons.

Return JSON:
{{
  "type": "print_and_sign" or "digital_submission" or "download",
  "description": "German description of what happens after completion",
  "submission_mode": "offline" or "online",
  "has_preview_button": true/false,
  "has_print_button": true/false,
  "preview_button_text": "exact button text or null",
  "print_button_text": "exact button text or null"
}}

Common patterns on MACH formsolutions:
- "Vorschau" / "Drucken" / "PDF" buttons present → print_and_sign, offline
  (Citizen prints the PDF, signs it, and mails it in)
- "Absenden" / "Einreichen" / "Online einreichen" → digital_submission, online
- "Herunterladen" / "Download" → download, offline
- "Ausfuellvorgang abschliessen" + "Vorschau"/"Drucken" → print_and_sign, offline

IMPORTANT: Identify the exact button text for preview/print buttons — we need the precise label.\
"""


def format_step_prompt(
    fields_json: str,
    page_title: str,
    step_text: str,
    headings: str,
    conditional_logic_json: str = "None detected.",
    auth_gate_info: str = "No auth gate detected.",
) -> str:
    return STEP_INTERPRETATION_PROMPT.format(
        fields_json=fields_json,
        page_title=page_title,
        step_text=step_text or "Not detected",
        headings=headings or "None",
        conditional_logic_json=conditional_logic_json,
        auth_gate_info=auth_gate_info,
    )


def format_mcp_spec_prompt(graph_json: str, form_title: str, source_url: str) -> str:
    return MCP_SPEC_GENERATION_PROMPT.format(
        graph_json=graph_json,
        form_title=form_title,
        source_url=source_url,
    )
