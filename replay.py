"""Deterministic weekly replay: no LLM, so nothing can be invented."""
import re

# resource -> (regex that finds it, [(state, regex)]); first matching state wins
RULES = {
    "Water source A": (r"\b(?:src|source|water)\s*a\b", [
        ("contaminated", r"contaminat|diesel sheen|test strip positive|stop using"),
        ("safe", r"looks clear|ok to use|tastes fine|\bsafe\b")]),
    "Water source B": (r"\b(?:src|source|water)\s*b\b|east creek", [
        ("contaminated", r"contaminat|test strip positive|strips? positive"),
        ("safe", r"clear flow|strips ok|test ok|approved for drinking|\bsafe\b")]),
    "Generator": (r"\bgen\b|generator", [
        ("not working", r"\bdied\b|wont restart|won't restart|shredded|not working"),
        ("running", r"running ok|belt replaced|repaired|load test ok")]),
    "Fuel": (r"\bfuel\b", [
        ("low", r"\blow\b|1/4 drum|running out"),
        ("sufficient", r"sufficient|full drum|refuel(?:l)?ed|delivered")]),
    "Road": (r"\broad\b|washout", [
        ("blocked", r"washout|blocked|cant pass|can't pass|cannot pass"),
        ("passable", r"passable|cleared|reopened")]),
}
NEGATIONS = r"no contamination|no odou?r|not contaminated"

def _detect(text, res):
    find, states = RULES[res]
    t = re.sub(NEGATIONS, "", text.lower())
    if not re.search(find, t):
        return None
    return next((s for s, p in states if re.search(p, t)), None)

def build_replay(notes):
    """notes: dicts from database.all_notes(). Returns timeline text (same shape the UI already shows)."""
    notes = [n for n in notes if n["day"] > 0 and n.get("source", "note") == "note"]
    if not notes:
        return "No notes yet."
    notes.sort(key=lambda n: (n["day"], n["time"], n["id"]))
    state, out, cur = {}, [], None
    for n in notes:
        if n["day"] != cur:
            cur = n["day"]; out += ["", f"Day {cur}:"]
        out.append(f"- {n['text']} ({n['author']}, {n['trust']})")
        for res in RULES:
            new = _detect(n["text"], res)
            if not new or new == state.get(res):
                continue
            old = state.get(res)
            out.append(f"Status changed: {res} changed from {old} to {new}." if old
                       else f"Status: {res} is {new}.")
            state[res] = new
    return "\n".join(out).strip()