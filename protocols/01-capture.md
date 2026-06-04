# NUMA Protocol 1: Capture — Structured LLM-Guided Interview

**Purpose**: Elicit and record the expert's tacit knowledge through a structured four-phase interview.

**Total Duration**: ~3.5 hours (can be split across 2 sessions)
**Participants**: 1 expert + 1 LLM interviewer (human facilitator optional)
**Prerequisites**: Pre-indexed documentation (manuals, SOPs, incident reports)

---

## Phase A — Role Mapping (30 min)

**Goal**: Build an initial concept map of the expert's domain and identify gaps between documented procedures and actual practice.

### Steps

1. **Opening** — LLM reads:
   > "Tell me about your role. What is your official title, and what do you actually do day-to-day? Start anywhere."

2. **Concept extraction** — LLM extracts entities and relationships in real-time:
   - Equipment, processes, materials, people, locations
   - Documented vs undocumented practices (flag discrepancies)

3. **Gap probe** — After 15 min, LLM asks:
   > "I've cross-referenced what you just described against the documentation I've indexed. I notice the manual says [X] but you do [Y]. Is that because [Y] is better, or because [X] is obsolete?"

4. **"Nobody knows" question** — LLM asks:
   > "What is the single most important thing you know that nobody else in your organization knows?"

5. **Output**: Initial concept graph (JSON nodes + edges) with gap annotations.

### Exit Criteria

- LLM can name the expert's top 3 responsibilities
- At least 2 documented-vs-actual discrepancies identified
- Concept graph has ≥10 nodes

---

## Phase B — Critical Cases (90 min)

**Goal**: Extract decision rationale from the expert's most difficult career moments.

### Steps

1. **Top 10 request** — LLM asks:
   > "Walk me through the ten most difficult moments of your career in this role. For each: what happened, what did you do, what alternatives did you consider, and why did you choose what you chose?"

2. **Per-case probing** — For each case, LLM asks:
   - "What would have happened if you chose differently?"
   - "Was there a moment where you almost made the wrong call? What stopped you?"
   - "Would the manual have told you to do the same thing?"
   - "If you had to train someone to handle this exact situation in 3 sentences, what would you say?"

3. **Cross-case pattern detection** — After case 5, LLM checks:
   > "I'm noticing a pattern: in cases [A], [B], and [C], you overrode the documented procedure in a similar way. Is that a deliberate heuristic you use?"

4. **Divergence quantification** — LLM asks for each override:
   > "On a scale of 1-5, how much did your actual decision differ from what the documentation recommends?"

### Exit Criteria

- All 10 cases narrated with decision rationale
- ≥3 documented-vs-actual divergences identified
- At least 1 pattern detected across cases

---

## Phase C — Inverse Verification (60 min)

**Goal**: Challenge the expert's testimony against pre-indexed documentation to surface contradictions and nuance.

### Steps

1. **Contradiction generation** — LLM selects 5-8 points where testimony differs from documentation and formulates challenges:
   > "The manual states calibration at 180°, but you mentioned using 175° on cold-start Mondays. Explain."

2. **Challenge delivery** — For each contradiction:
   - Read the documented rule
   - Read the expert's recorded statement
   - Ask: "Which is correct? Both? Under what conditions does each apply?"

3. **Condition capture** — LLM records the conditions under which each rule applies:
   - "When temperature < X" or "On equipment built before year Y"
   - Exceptions, edge cases, seasonal variations

4. **Third-option detection** — LLM checks for unstated middle grounds:
   > "Is there a third option neither the manual nor your first answer covers?"

### Exit Criteria

- All 5-8 contradictions resolved or acknowledged as genuine conflicts
- Conditional applicability rules recorded for each divergence
- At least 2 "third options" discovered

---

## Phase D — The Unwritten (30 min)

**Goal**: Capture the knowledge that exists in no document, no manual, and no training program.

### Steps

1. **Legacy question** — LLM asks:
   > "What should your successor know that appears in no document, no manual, and no training program?"

2. **Successor letter** — LLM asks:
   > "If you could write a 500-word letter to your successor, starting with 'The one thing they won't tell you is...', what would it say?"

3. **Near-miss inventory** — LLM asks:
   > "Tell me about a time you narrowly avoided a disaster. What was the warning sign? How did you know to act?"

4. **Five whys** — LLM drills into key claims using the Five Whys technique.

5. **Closure** — LLM asks:
   > "Is there anything you wanted to say that we haven't covered?"

### Exit Criteria

- ≥3 pieces of unwritten knowledge captured
- Successor letter drafted
- Near-miss with warning signs documented

---

## Output Format

After all 4 phases, the LLM produces a structured JSON document:

```json
{
  "expert": {
    "name": "...",
    "role": "...",
    "years_experience": 0,
    "domain": "..."
  },
  "knowledge": {
    "facts": [
      {
        "statement": "Calibrate at 180°C per manual",
        "source": "manual",
        "weight": 0.3,
        "conditions": []
      }
    ],
    "judgments": [
      {
        "statement": "Use 175°C on cold-start Mondays",
        "rationale": "Right gasket softer than spec on cold days",
        "source": "interview_phase_b",
        "weight": 0.7,
        "conditions": ["ambient_temp < 5°C", "monday_morning"]
      }
    ],
    "intuitions": [
      {
        "statement": "Listen for a clicking sound on startup — that means gasket is binding",
        "source": "interview_phase_d",
        "weight": 0.5,
        "context": "near-miss inventory"
      }
    ]
  },
  "concept_graph": {
    "nodes": ["K-700", "gasket", "calibration"],
    "edges": [["K-700", "gasket", "contains"], ["gasket", "calibration", "affected_by"]]
  },
  "validation_gap_score": 0.85,
  "duration_minutes": 210,
  "session_id": "..."
}
```
