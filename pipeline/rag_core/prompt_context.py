from typing import List, Optional


def build_context_block(
    rag_context: str,
    enrich_context: str,
    suggested_codes: Optional[List[dict]] = None,
) -> str:
    parts = []

    if rag_context:
        parts.append(f"Relevant medical reference information:\n{rag_context}")

    if suggested_codes:
        lines = ["Suggested Codes:"]
        for item in suggested_codes:
            code = item.get("code", "")
            desc = item.get("description", "")
            symptom = item.get("matched_symptom", "")
            if code and desc:
                lines.append(f"- {code}: {desc} (matched symptom: {symptom})")
        if len(lines) > 1:
            parts.append("\n".join(lines))

    if enrich_context:
        parts.append(enrich_context)

    return "\n\n".join(parts) + "\n" if parts else ""
