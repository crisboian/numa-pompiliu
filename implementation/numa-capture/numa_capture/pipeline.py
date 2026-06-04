"""NUMA Capture — interview pipeline orchestrator."""

from __future__ import annotations

import json
import logging

from numa_capture.models import InterviewSession, Phase, PhaseResult
from numa_capture.phases import run_phase_a, run_phase_b, run_phase_c, run_phase_d

logger = logging.getLogger("numa-capture")

PHASE_RUNNERS = {
    Phase.A: run_phase_a,
    Phase.B: run_phase_b,
    Phase.C: run_phase_c,
    Phase.D: run_phase_d,
}


class CapturePipeline:
    """Orchestrates the 4-phase NUMA Capture interview."""

    def __init__(self, expert_name: str = "", expert_role: str = "", domain: str = "") -> None:
        self.session = InterviewSession(
            expert_name=expert_name,
            expert_role=expert_role,
            domain=domain,
        )

    def run_all(self) -> InterviewSession:
        """Execute all 4 phases in sequence."""
        self.session.status = "in_progress"

        for phase in [Phase.A, Phase.B, Phase.C, Phase.D]:
            logger.info("Starting Phase %s (%s)...", phase.value, PHASE_RUNNERS[phase].__name__)
            runner = PHASE_RUNNERS[phase]
            result = runner(self.session)
            self.session.add_phase(result)
            logger.info(
                "Phase %s complete: %d knowledge items, %d concepts",
                phase.value,
                len(result.knowledge_items),
                len(result.concepts),
            )

        self.session.status = "completed"
        logger.info(
            "Capture complete: %d phases, %d min total, %d knowledge items",
            len(self.session.phases),
            self.session.total_duration_minutes,
            self._total_items(),
        )

        return self.session

    def _total_items(self) -> int:
        return sum(
            len(p.knowledge_items)
            for p in self.session.phases.values()
        )

    def get_all_prompts(self) -> list[dict]:
        """Return all prompts used across phases (for LLM orchestration)."""
        prompts = []
        for phase in [Phase.A, Phase.B, Phase.C, Phase.D]:
            runner = PHASE_RUNNERS[phase]
            if phase == Phase.A:
                from numa_capture.phases import describe_phase_a, probe_gaps, nobody_knows
                for p in [describe_phase_a(), probe_gaps(), nobody_knows()]:
                    prompts.append({"phase": p.phase.value, "order": p.order, "text": p.text})
            elif phase == Phase.B:
                from numa_capture.phases import top_ten_prompt, pattern_detection, divergence_scale
                for p in [top_ten_prompt(), pattern_detection(), divergence_scale()]:
                    prompts.append({"phase": p.phase.value, "order": p.order, "text": p.text})
            elif phase == Phase.C:
                from numa_capture.phases import generate_contradiction, condition_capture
                prompts.append({"phase": "inverse_verification", "order": 1, "text": generate_contradiction("[fact]", "[testimony]").text})
                prompts.append({"phase": "inverse_verification", "order": 2, "text": condition_capture().text})
            elif phase == Phase.D:
                from numa_capture.phases import successor_letter, near_miss, closure
                for p in [successor_letter(), near_miss(), closure()]:
                    prompts.append({"phase": p.phase.value, "order": p.order, "text": p.text})
        return prompts

    def export_json(self) -> str:
        """Export the complete session as JSON."""
        return json.dumps(
            json.loads(self.session.model_dump_json()),
            indent=2,
            ensure_ascii=False,
        )


def main() -> None:
    """Run the capture pipeline and print results."""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    expert_name = sys.argv[1] if len(sys.argv) > 1 else "Pepe García"
    expert_role = sys.argv[2] if len(sys.argv) > 2 else "Senior Operator"
    domain = sys.argv[3] if len(sys.argv) > 3 else "Industrial Safety"

    pipeline = CapturePipeline(
        expert_name=expert_name,
        expert_role=expert_role,
        domain=domain,
    )

    session = pipeline.run_all()
    output = pipeline.export_json()

    print(output)


if __name__ == "__main__":
    main()
