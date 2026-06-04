"""NUMA Benchmark — standardized evaluation questions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BenchmarkQuestion:
    """A benchmark question with expected answer and cognitive type."""

    id: str
    question: str
    cognitive_type: str
    expected_answer: str
    keywords: list[str] = field(default_factory=list)


QUESTIONS: list[BenchmarkQuestion] = [
    BenchmarkQuestion(
        id="Q1",
        question="What is the operating range of the K-700?",
        cognitive_type="factual_lookup",
        expected_answer="170–190°C",
        keywords=["operating range", "K-700", "170", "190", "temperature"],
    ),
    BenchmarkQuestion(
        id="Q2",
        question="What startup procedure should be followed on cold-start Mondays?",
        cognitive_type="exception_handling",
        expected_answer="Reduce calibration temperature to 175°C",
        keywords=[
            "cold-start",
            "Monday",
            "175",
            "calibration",
            "reduce",
            "temperature",
        ],
    ),
    BenchmarkQuestion(
        id="Q3",
        question="Why does the right gasket fail more often than the left?",
        cognitive_type="causal_reasoning",
        expected_answer="The right-hand gasket is softer than specification",
        keywords=["right gasket", "soft", "specification", "gasket", "fails"],
    ),
    BenchmarkQuestion(
        id="Q4",
        question="List steps to calibrate the pressure valve on the K-700.",
        cognitive_type="procedural_sequencing",
        expected_answer="Standard calibration procedure takes 15 minutes; after major maintenance, run calibration twice.",
        keywords=["calibration", "15 minutes", "pressure valve", "maintenance"],
    ),
    BenchmarkQuestion(
        id="Q5",
        question="The manual says 190°C but Pepe says 185°C — what temperature should you use and why?",
        cognitive_type="judgment_conflict",
        expected_answer="185°C — the gasket is softer than spec and melted at 193°C in incident #234.",
        keywords=[
            "185",
            "gasket",
            "softer",
            "incident",
            "Pepe",
            "melted",
            "safe limit",
        ],
    ),
    BenchmarkQuestion(
        id="Q6",
        question="What warning signs precede a gasket failure on the K-700?",
        cognitive_type="pattern_recognition",
        expected_answer="Clicking sound on startup (gasket binding) and pressure gauge needle vibration between 1.2–1.4 bar.",
        keywords=["clicking sound", "binding", "pressure", "vibrate", "gauge"],
    ),
    BenchmarkQuestion(
        id="Q7",
        question="Should the K-700 operate at 195°C?",
        cognitive_type="multi_tier_synthesis",
        expected_answer="No. Maximum safe operating temperature is 185°C based on expert judgment and incident evidence.",
        keywords=["185", "no", "195", "exceed", "gasket", "melted"],
    ),
]

COGNITIVE_TYPES = [
    "factual_lookup",
    "exception_handling",
    "causal_reasoning",
    "procedural_sequencing",
    "judgment_conflict",
    "pattern_recognition",
    "multi_tier_synthesis",
]
