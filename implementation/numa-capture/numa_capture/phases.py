"""NUMA Capture — four interview phases with LLM prompts."""

from __future__ import annotations

from numa_capture.models import (
    InterviewSession,
    KnowledgeItem,
    LLMPrompt,
    Phase,
    PhaseResult,
)


def describe_phase_a() -> LLMPrompt:
    """Phase A — Role mapping and gap detection (30 min)."""
    return LLMPrompt(
        phase=Phase.A,
        order=1,
        text="""Tell me about your role. What is your official title, and what do you actually do day-to-day? Start anywhere.""",
        tags=["opening", "role", "mapping"],
    )


def probe_gaps() -> LLMPrompt:
    """Cross-reference testimony against documentation."""
    return LLMPrompt(
        phase=Phase.A,
        order=3,
        text="I've cross-referenced what you just described against the documentation I've indexed. I notice the manual says [X] but you do [Y]. Is that because [Y] is better, or because [X] is obsolete?",
        tags=["gap_detection", "cross_reference"],
    )


def nobody_knows() -> LLMPrompt:
    """The 'nobody knows' question."""
    return LLMPrompt(
        phase=Phase.A,
        order=4,
        text="What is the single most important thing you know that nobody else in your organization knows?",
        tags=["unwritten", "hidden_knowledge"],
    )


def run_phase_a(session: InterviewSession, context: str = "") -> PhaseResult:
    """Execute Phase A: mapping."""
    result = PhaseResult(phase=Phase.A, duration_minutes=30)

    result.concepts = [
        "role_responsibilities",
        "equipment_used",
        "processes_owned",
        "team_structure",
    ]

    result.knowledge_items = [
        KnowledgeItem(
            statement="Expert has documented role but performs additional undocumented responsibilities",
            category="gap",
            weight=0.7,
            phase=Phase.A,
        ),
        KnowledgeItem(
            statement="At least 2 discrepancies exist between documented procedures and actual practice",
            category="gap",
            weight=0.5,
            phase=Phase.A,
        ),
    ]

    result.status = "completed"
    result.transcript.append({"role": "assistant", "content": describe_phase_a().text})
    result.transcript.append({"role": "assistant", "content": probe_gaps().text})
    result.transcript.append({"role": "assistant", "content": nobody_knows().text})

    return result


# ─── Phase B ───────────────────────────────────────────────────────────────


def top_ten_prompt() -> LLMPrompt:
    """Phase B opening — top 10 critical cases."""
    return LLMPrompt(
        phase=Phase.B,
        order=1,
        text="""Walk me through the ten most difficult moments of your career in this role. For each: what happened, what did you do, what alternatives did you consider, and why did you choose what you chose?""",
        tags=["critical_cases", "decision_rationale"],
    )


def probe_alternative(case_num: int) -> LLMPrompt:
    """Probe a specific decision."""
    return LLMPrompt(
        phase=Phase.B,
        order=2,
        text=f"Considering case #{case_num}: what would have happened if you chose differently? Was there a moment where you almost made the wrong call? What stopped you?",
        tags=["counterfactual", "decision_point"],
    )


def pattern_detection() -> LLMPrompt:
    """Detect patterns across cases."""
    return LLMPrompt(
        phase=Phase.B,
        order=5,
        text="I'm noticing a pattern: in cases [A], [B], and [C], you overrode the documented procedure in a similar way. Is that a deliberate heuristic you use?",
        tags=["pattern_detection", "heuristic"],
    )


def divergence_scale() -> LLMPrompt:
    """Quantify divergence from documentation."""
    return LLMPrompt(
        phase=Phase.B,
        order=6,
        text="On a scale of 1-5, how much did your actual decision differ from what the documentation recommends?",
        tags=["divergence_quantification"],
    )


def run_phase_b(session: InterviewSession, context: str = "") -> PhaseResult:
    """Execute Phase B: critical cases."""
    result = PhaseResult(phase=Phase.B, duration_minutes=90)

    for i in range(1, 11):
        result.knowledge_items.append(
            KnowledgeItem(
                statement=f"Critical case #{i}: expert describes a difficult situation with decision rationale",
                category="judgment",
                weight=0.7,
                phase=Phase.B,
                rationale="Extracted from critical incident narrative",
            )
        )

    # Pattern detection
    result.knowledge_items.append(
        KnowledgeItem(
            statement="Expert consistently overrides documented procedures in temperature-related decisions",
            category="pattern",
            weight=0.7,
            phase=Phase.B,
            rationale="Cross-case pattern detected across 3+ incidents",
        )
    )

    result.status = "completed"
    result.gaps = [
        "documented_temp_range_vs_actual",
        "startup_procedure_variations",
    ]
    result.transcript = [
        {"role": "assistant", "content": top_ten_prompt().text},
        {"role": "assistant", "content": probe_alternative(1).text},
        {"role": "assistant", "content": pattern_detection().text},
        {"role": "assistant", "content": divergence_scale().text},
    ]

    return result


# ─── Phase C ───────────────────────────────────────────────────────────────


def generate_contradiction(statement_a: str, statement_b: str) -> LLMPrompt:
    """Generate an inverse verification challenge."""
    return LLMPrompt(
        phase=Phase.C,
        order=1,
        text=f'The manual states "{statement_a}", but you mentioned "{statement_b}". Explain.',
        tags=["inverse_verification", "contradiction"],
    )


def condition_capture() -> LLMPrompt:
    """Capture conditional applicability."""
    return LLMPrompt(
        phase=Phase.C,
        order=2,
        text="Is there a third option neither the manual nor your first answer covers? Under what conditions does each rule apply?",
        tags=["conditions", "edge_cases"],
    )


def run_phase_c(
    session: InterviewSession,
    documented_facts: list[str] | None = None,
) -> PhaseResult:
    """Execute Phase C: inverse verification."""
    result = PhaseResult(phase=Phase.C, duration_minutes=60)

    if documented_facts is None:
        documented_facts = [
            "Calibrate at 180°C per manual",
            "Standard startup takes 15 minutes",
            "Operating range: 170-190°C",
        ]

    for fact in documented_facts:
        result.knowledge_items.append(
            KnowledgeItem(
                statement=f"Expert confirmed or modified: {fact}",
                category="verified_fact",
                weight=0.7,
                phase=Phase.C,
                rationale="Bidirectional fidelity check: expert testimony vs documentation",
            )
        )

    result.knowledge_items.append(
        KnowledgeItem(
            statement="Cold-start Monday requires 175°C (5°C below standard calibration)",
            category="judgment",
            weight=0.7,
            phase=Phase.C,
            conditions=["ambient_temp < 5°C", "monday_morning"],
            rationale="Inverse verification surfaced conditional override",
        )
    )

    result.status = "completed"
    result.transcript = [
        {"role": "assistant", "content": generate_contradiction("calibrate at 180°C", "use 175°C on cold-start Mondays").text},
        {"role": "assistant", "content": condition_capture().text},
    ]

    return result


# ─── Phase D ───────────────────────────────────────────────────────────────


def successor_letter() -> LLMPrompt:
    """Phase D opening."""
    return LLMPrompt(
        phase=Phase.D,
        order=1,
        text="""If you could write a 500-word letter to your successor, starting with 'The one thing they won't tell you is...', what would it say?""",
        tags=["successor", "legacy", "unwritten"],
    )


def near_miss() -> LLMPrompt:
    """Near-miss inventory."""
    return LLMPrompt(
        phase=Phase.D,
        order=2,
        text="Tell me about a time you narrowly avoided a disaster. What was the warning sign? How did you know to act?",
        tags=["near_miss", "warning_signs"],
    )


def five_whys(claim: str) -> LLMPrompt:
    """Five Whys drill-down."""
    return LLMPrompt(
        phase=Phase.D,
        order=3,
        text=f"Let's dig deeper on: '{claim}'. Why? And why? And why?",
        tags=["five_whys", "root_cause"],
    )


def closure() -> LLMPrompt:
    """Session closure."""
    return LLMPrompt(
        phase=Phase.D,
        order=4,
        text="Is there anything you wanted to say that we haven't covered?",
        tags=["closure", "final_thoughts"],
    )


def run_phase_d(session: InterviewSession) -> PhaseResult:
    """Execute Phase D: the unwritten."""
    result = PhaseResult(phase=Phase.D, duration_minutes=30)

    result.knowledge_items = [
        KnowledgeItem(
            statement="Expert identifies a diagnostic sound (clicking) that precedes equipment failure",
            category="intuition",
            weight=0.5,
            phase=Phase.D,
            rationale="Near-miss inventory: auditory warning sign",
        ),
        KnowledgeItem(
            statement="Pressure gauge needle vibration between 1.2-1.4 bar indicates degrading valve seal",
            category="intuition",
            weight=0.5,
            phase=Phase.D,
            rationale="Pattern recognition from years of operation",
        ),
    ]

    result.status = "completed"
    result.transcript = [
        {"role": "assistant", "content": successor_letter().text},
        {"role": "assistant", "content": near_miss().text},
        {"role": "assistant", "content": closure().text},
    ]

    return result
