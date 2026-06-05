# NUMA Protocol 5: Maintenance — Living Knowledge Cycle

**Purpose**: Keep the knowledge representation accurate over time by detecting contradictions, incorporating new information, and preserving an auditable history.

**Cycle**: Every 6 months (configurable to 3 months for fast-changing domains)
**Trigger**: Cron job or manual invocation
**Cost**: ~30 min per maintenance cycle

---

## Architecture

```
Every 6 months
    │
    ▼
┌────────────────────────────────────┐
│  1. Regulatory Check               │
│  ── Have applicable standards      │
│     changed?                       │
└────────────────────────────────────┘
    │
    ▼
┌────────────────────────────────────┐
│  2. Incident Review                │
│  ── Do new incidents contradict    │
│     captured knowledge?            │
└────────────────────────────────────┘
    │
    ▼
┌────────────────────────────────────┐
│  3. Successor Feedback             │
│  ── Has successor discovered gaps? │
└────────────────────────────────────┘
    │
    ▼
┌────────────────────────────────────┐
│  4. Contradiction Resolution       │
│  ── Generate alert for human       │
│     review (never silent overwrite)│
└────────────────────────────────────┘
    │
    ▼
┌────────────────────────────────────┐
│  5. Knowledge Update               │
│  ── Index new facts, flag changed  │
│     facts                          │
└────────────────────────────────────┘
    │
    ▼
┌────────────────────────────────────┐
│  6. Audit Log                      │
│  ── Record what changed and why    │
└────────────────────────────────────┘
```

---

## Step 1: Regulatory Check

### Automated
1. For each regulatory standard referenced in the Facts tier, check:
   - Is there a newer version? (e.g., ISO 45001:2023 → ISO 45001:2026)
   - Have specific clauses changed?
2. Search the web for changes using:
   > Query: "{regulation_name} {year_old} update {year_new} changes"
3. Compare changes against stored facts
4. Flag any fact that contradicts new regulations

### Output
```json
{
  "regulation": "ISO 45001:2023",
  "status": "updated",
  "changes": [
    {
      "clause": "5.3",
      "old": "Management review quarterly",
      "new": "Management review monthly",
      "impact": "FACT: 'Safety review every 3 months' is now incorrect"
    }
  ],
  "action_required": true
}
```

---

## Step 2: Incident Review

1. Query incident reporting system or database for new incidents since last maintenance cycle
2. For each incident, determine:
   - Does it relate to captured knowledge?
   - Does it validate or contradict the knowledge?
3. If contradictory:
   - Extract the specific knowledge that was violated
   - Note the incident details (date, equipment, outcome)
   - Flag for resolution

### Incident-Contradiction Patterns

| Incident | Captured Knowledge | Flag |
|----------|-------------------|------|
| Melted gasket at 180°C | "Never exceed 185°C" | ⚠️ Contradiction — failure occurred below the stated threshold |
| Successful operation at 200°C | "Max 190°C" | ⚠️ Contradiction — equipment survived above the stated limit |
| New procedure eliminated gasket failures | "Use 175°C on cold-start Mondays" | ⚠️ Obsolete — root cause eliminated |

---

## Step 3: Successor Feedback

1. Query the successor (the person who filled the expert's role):
   > "In the last 6 months, have you encountered any situation where the Numa knowledge base gave inaccurate or incomplete guidance?"

2. If yes, capture the specific gap:
   > "What was the situation? What answer did Numa give? What answer should it have given?"

3. Classify the gap:
   - **Missing knowledge**: The expert never covered this topic
   - **Outdated knowledge**: The expert's knowledge was correct then, but conditions changed
   - **Erroneous knowledge**: The expert was wrong
   - **Context missing**: The knowledge is correct but conditions/limits weren't properly recorded

---

## Step 4: Contradiction Resolution

### Golden Rule
**Never silently overwrite existing knowledge. Always generate an alert for human review.**

### Alert Format
```json
{
  "alert_id": "alert-2026-06-15-001",
  "type": "contradiction",
  "severity": "medium",
  "existing_knowledge": {
    "statement": "Never exceed 185°C",
    "source": "Pepe García (session 2026-03-15)",
    "tier": "judgment",
    "weight": 0.7
  },
  "new_evidence": {
    "statement": "Gasket melted at 180°C on unit K-703",
    "source": "Incident #456 (2026-06-10)",
    "tier": "fact"
  },
  "recommended_action": "Schedule review: threshold may need adjustment for newer units",
  "human_review_required": true
}
```

### Resolution Options for Human Review

1. **Update**: New info replaces old (document why)
2. **Augment**: Both are true under different conditions (add conditions)
3. **Deprecate**: Old knowledge is no longer valid (mark as deprecated, keep in history)
4. **Reject**: New info is anomalous (document why it doesn't apply)

---

## Step 5: Knowledge Update

After human review:

1. **New facts**: Index into ChromaDB + add nodes to Graphify
2. **Changed facts**: Version the old fact (increment version counter), add new version
3. **Deprecated facts**: Mark as `status: deprecated` (never delete — audit trail)
4. **Re-weighted facts**: Update tier weights if needed

### Versioning
```json
{
  "id": "k700_temp_limit",
  "versions": [
    {"value": "185°C", "effective": "2026-03-15", "status": "superseded", "superseded_by": "v2"},
    {"value": "175°C", "effective": "2026-09-15", "status": "active", "source": "incident_456"}
  ],
  "audit": [
    {"date": "2026-09-15", "action": "update", "reason": "Gasket melted at 180°C on unit K-703", "reviewer": "Maria López"}
  ]
}
```

---

## Step 6: Audit Log

After every maintenance cycle, produce a summary report:

```markdown
## NUMA Maintenance Report — June 2026

**Domain**: Industrial Safety (K-700 line)
**Knowledge base**: Pepe García, captured 2026-03-15

### Changes Made
| Item | Type | Action | Reason |
|------|------|--------|--------|
| K-700 temp limit | Judgment | Updated 185→175°C | Incident #456 |
| ISO 45001 clause 5.3 | Fact | Updated "quarterly"→"monthly" | Regulation change |

### Open Alerts
| ID | Severity | Summary |
|----|----------|---------|
| ALERT-001 | Medium | Gasket threshold may need re-evaluation |
| ALERT-002 | Low | No successor feedback received |

### Statistics
- Facts checked: 47
- New facts added: 3
- Facts updated: 2
- Facts deprecated: 1
- Contradictions found: 2
- Alerts generated: 2
- Human review actions: 1 (pending)

### Next maintenance cycle: December 2026
```

---

## Edge Cases

| Scenario | Handling |
|----------|----------|
| No changes detected | Report "No changes. Next cycle: {date}" — close maintenance |
| Expert still available | Optional: supplement capture on flagged topics |
| Successor doesn't respond | Escalate after 2 missed cycles |
| Mass regulation change | Flag all affected facts at once; human review batches them |
| Silent silent alarm | If no incidents reported, trust is unchanged |
