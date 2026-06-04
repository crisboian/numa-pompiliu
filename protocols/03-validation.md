# NUMA Protocol 3: Validation — Bidirectional Fidelity Check

**Purpose**: Verify that the captured knowledge representation accurately reflects the expert's expertise before they depart.

**Duration**: ~1 hour
**Participants**: 1 expert + LLM
**Prerequisite**: Protocols 1 (Capture) and 2 (Structure) completed

---

## Step 1: Generate Examination Questions

The LLM generates 20 questions spanning all three knowledge tiers, distributed as follows:

| Tier | Questions | Cognitive Types |
|------|-----------|-----------------|
| Facts | 6 | Factual lookup, procedural sequencing |
| Judgments | 8 | Exception handling, causal reasoning, judgment under conflict |
| Intuitions | 4 | Pattern recognition, near-miss detection |
| Cross-tier | 2 | Multi-tier synthesis (requires facts + judgment + intuition) |

### Cognitive Type Distribution

| Cognitive Type | Count | Example |
|----------------|-------|---------|
| Factual lookup | 4 | "What is the operating range of the K-700?" |
| Procedural sequencing | 2 | "List the startup steps in order." |
| Exception handling | 4 | "What do you do when the pressure exceeds 190° on a cold day?" |
| Causal reasoning | 4 | "Why does the gasket fail more often in winter?" |
| Judgment under conflict | 4 | "The manual says 190°, Pepe says 185°. What do you do and why?" |
| Pattern recognition | 2 | "What warning signs precede a gasket failure?" |

### Question Generation Prompt (for LLM)

```
Generate {count} examination questions for expert {name} in domain {domain}.

Knowledge available:
- Facts: {list_facts}
- Judgments: {list_judgments}  
- Intuitions: {list_intuitions}

Cognitive type: {type}

Rules:
1. Questions must be answerable from the captured knowledge
2. Questions must be meaningful (no trivia)
3. Cross-tier questions must require combining at least 2 tiers
4. Each question must have a definite correct answer
```

---

## Step 2: Expert Answers (Ground Truth)

The expert answers all 20 questions **before** seeing any Numa answer.

- **Format**: Free-text answers
- **Recording**: Full transcript saved
- **Duration**: ~30 minutes for 20 questions
- **Constraints**: Expert cannot consult documentation — answers must be from memory

---

## Step 3: Numa Answers

Numa answers the same 20 questions using **only** the captured knowledge (Protocols 1+2).

- **Mode**: KGAA+RRF retrieval
- **Format**: Answer + confidence level + source citations
- **Example**:
  > **Q**: Can the K-700 operate at 195°?
  > **A**: No. Pepe García (session 2026-03-15): "Never exceed 185° even though the manual says 190°." Incident #234 (2019): right gasket melted at 193°C. **Confidence: High**

---

## Step 4: Expert Rating

For each question, the expert rates Numa's response on a 1–5 scale:

| Rating | Meaning |
|--------|---------|
| 1 | Wrong — would cause operational error |
| 2 | Incomplete — misses critical nuance |
| 3 | Acceptable — technically correct but lacks depth |
| 4 | Good — captures the essential reasoning |
| 5 | Perfect — indistinguishable from expert's own answer |

---

## Step 5: Pass/Fail Determination

```
mean_score = average of all 20 ratings

IF mean_score >= 4.0:
    → PASS — proceed to attestation
ELSE:
    → FAIL — identify deficient topics:
        1. For each question with rating < 4, extract the knowledge gap
        2. Reopen the Capture protocol for deficient topics only
        3. Re-run Validation on the supplemented knowledge
        4. Repeat until mean >= 4.0 (max 3 iterations)
```

**Threshold rationale**: 4.0 is deliberately conservative — requires "Good or better" on average, not merely "Acceptable." Configurable in protocol settings.

---

## Step 6: Expert Attestation

If PASS, the expert signs (digitally or physically):

> **Attestation of Knowledge Fidelity**
>
> I, {expert_name}, confirm that the digital knowledge representation produced by the Numa methodology reflects my expertise with sufficient fidelity for operational use.
>
> I understand that:
> - This representation will be used to answer questions in my absence
> - Any errors or omissions are my responsibility to flag now
> - The representation will be reviewed every 6 months
>
> Mean fidelity score: {mean_score}/5.0
> Questions passed: {count_passed}/20
> Date: {date}
> Signature: _________________________

---

## Post-Validation Actions

1. **Knowledge freeze**: Lock the validated knowledge from further edits
2. **Session archiving**: Save full validation transcript to Engram
3. **Deployment flag**: Mark knowledge as "production-ready" for the Access protocol
