"""NUMA Capture Web — LLM interviewer integration.

Calls DeepSeek V4 Flash to generate interview questions and analyze answers.
Falls back to template prompts if the LLM is unavailable.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("numa-capture-llm")

# Default to DeepSeek — user can override via env
LLM_API_URL = os.environ.get(
    "NUMA_LLM_URL", "https://api.deepseek.com/v1/chat/completions"
)
LLM_API_KEY = os.environ.get("NUMA_LLM_KEY", "")
LLM_MODEL = os.environ.get("NUMA_LLM_MODEL", "deepseek-chat")  # V4 Flash

DEFAULT_TEMPERATURE = 0.7


# ─── Phase definitions ─────────────────────────────────────────────────────


PHASE_DEFINITIONS = {
    "A": {
        "name": "Role Mapping & Gap Detection",
        "duration": "30 min",
        "description": "Mapeamos tu rol, responsabilidades y detectamos gaps entre la documentación y la práctica real.",
        "opening": "Cuéntame sobre tu rol. ¿Cuál es tu título oficial y qué haces realmente en el día a día? Empieza por donde quieras.",
        "prompts": [
            "¿Qué equipos, herramientas o sistemas usas a diario que no aparecen en tu descripción de puesto?",
            "He contrastado lo que me dices con la documentación que tengo indexada. ¿Hay algo en los manuales que ya no se haga así, o que se haga diferente?",
            "¿Cuál es la cosa más importante que sabes y que nadie más en tu organización sabe?",
        ],
        "tags": ["opening", "role", "mapping", "gap_detection", "hidden_knowledge"],
        "llm_system": """Eres un entrevistador experto en captura de conocimiento tácito. 
Estás en la Fase A (mapeo de rol y detección de gaps, 30 min).

Tu objetivo:
1. Entender el rol REAL del experto (no el oficial)
2. Identificar gaps entre documentación y práctica
3. Descubrir conocimiento que no está escrito

Sé conversacional, haz preguntas de seguimiento basadas en las respuestas. 
Si el experto da una respuesta genérica, profundiza con un "¿Puedes darme un ejemplo concreto?".
Si menciona algo que no entiendes, pídele que te lo explique como si fueras un novato.""",
    },
    "B": {
        "name": "Critical Incidents",
        "duration": "90 min",
        "description": "Repasamos los 10 momentos más difíciles de tu carrera. Para cada uno: qué pasó, qué hiciste, qué alternativas consideraste y por qué elegiste esa opción.",
        "opening": "Vamos a repasar los diez momentos más difíciles de tu carrera en este rol. Para cada uno: ¿qué pasó, qué hiciste, qué alternativas consideraste y por qué elegiste esa opción? Empecemos con el primero.",
        "prompts": [
            "¿Qué habría pasado si hubieras elegido diferente? ¿Hubo un momento en el que casi tomas la decisión equivocada? ¿Qué te detuvo?",
            "Veo un patrón: en varios casos te saltaste el procedimiento documentado de forma similar. ¿Es una heurística deliberada?",
            "Del 1 al 5, ¿cuánto se desvió tu decisión real de lo que recomienda la documentación?",
        ],
        "tags": ["critical_cases", "decision_rationale", "counterfactual", "pattern_detection"],
        "llm_system": """Eres un entrevistador experto en captura de conocimiento tácito.
Estás en la Fase B (incidentes críticos, 90 min).

Tu objetivo:
1. Extraer 10 casos críticos con detalle
2. Capturar el razonamiento detrás de cada decisión
3. Identificar patrones entre casos
4. Cuantificar la divergencia con la documentación

Estructura para cada caso:
- Contexto: ¿qué pasó?
- Acción: ¿qué hiciste?
- Alternativas: ¿qué más consideraste?
- Razón: ¿por qué esa opción?
- Contra factual: ¿qué habría pasado si hacías otra cosa?

Si el experto se salta detalles, pídele más. Si repite patrones, señáleselos.""",
    },
    "C": {
        "name": "Inverse Verification",
        "duration": "60 min",
        "description": "Contrastamos lo que has dicho con la documentación existente. Buscamos contradicciones y condiciones de contorno.",
        "opening": "Voy a contrastar lo que me has contado con la documentación que tengo. Ayúdame a resolver las contradicciones.",
        "prompts": [
            "¿Hay una tercera opción que no está ni en el manual ni en tu primera respuesta? ¿Bajo qué condiciones aplica cada regla?",
            "¿Qué excepciones conoces que no están documentadas?",
        ],
        "tags": ["inverse_verification", "contradiction", "conditions", "edge_cases"],
        "llm_system": """Eres un entrevistador experto en captura de conocimiento tácito.
Estás en la Fase C (verificación inversa, 60 min).

Tu objetivo:
1. Identificar contradicciones entre el testimonio del experto y la documentación
2. Capturar condiciones de contorno ("esto aplica cuando...")
3. Descubrir excepciones no documentadas
4. Validar la fiabilidad de cada afirmación

Sé escéptico pero respetuoso. Pregunta "¿Estás seguro? ¿Cómo lo sabes?" 
Busca condiciones: ¿bajo qué circunstancias NO aplica esta regla?""",
    },
    "D": {
        "name": "The Unwritten",
        "duration": "30 min",
        "description": "Lo que no aparece en ningún documento: intuiciones, señales de advertencia, conocimiento que se lleva el experto.",
        "opening": "Si pudieras escribir una carta de 500 palabras a tu sucesor, empezando con 'Lo que no te van a contar es...', ¿qué le dirías?",
        "prompts": [
            "Cuéntame una vez que casi evitaste un desastre por los pelos. ¿Cuál fue la señal de advertencia? ¿Cómo supiste que tenías que actuar?",
            "¿Hay algo que quisieras decir que no hemos cubierto?",
        ],
        "tags": ["successor", "legacy", "unwritten", "near_miss", "closure"],
        "llm_system": """Eres un entrevistador experto en captura de conocimiento tácito.
Estás en la Fase D (lo no escrito, 30 min).

Tu objetivo:
1. Capturar conocimiento intuitivo (corazonadas, señales, sexto sentido)
2. Extraer near-misses (casi accidentes)
3. Consejos para el sucesor
4. Cierre emocional de la entrevista

Esta es la fase más personal. Sé empático. Valora el conocimiento que el experto
se está llevando. Pregunta por señales sutiles que solo él/ella reconoce.""",
    },
}

PHASE_ORDER = ["A", "B", "C", "D"]


# ─── LLM caller ────────────────────────────────────────────────────────────


async def call_llm(
    messages: list[dict[str, str]],
    system_prompt: str = "",
    temperature: float = DEFAULT_TEMPERATURE,
) -> str | None:
    """Call the LLM and return the response text."""
    if not LLM_API_KEY:
        logger.warning("No NUMA_LLM_KEY set, using template prompts")
        return None

    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                LLM_API_URL,
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": LLM_MODEL,
                    "messages": full_messages,
                    "temperature": temperature,
                    "max_tokens": 512,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return None


# ─── Question generation ───────────────────────────────────────────────────


def get_next_template_prompt(session_data: dict[str, Any]) -> str | None:
    """Get the next template prompt based on current phase and order."""
    phase = session_data["current_phase"]
    phase_order = session_data["phase_order"]
    phase_def = PHASE_DEFINITIONS.get(phase)

    if not phase_def:
        return None

    # Opening question
    if phase_order == 0:
        return phase_def["opening"]

    # Follow-up prompts
    idx = phase_order - 1
    prompts = phase_def["prompts"]
    if idx < len(prompts):
        return prompts[idx]

    return None


async def generate_next_question(
    session_data: dict[str, Any], conversation: list[dict[str, str]]
) -> str | None:
    """Generate the next interview question using LLM or fallback to templates."""
    phase = session_data["current_phase"]
    phase_def = PHASE_DEFINITIONS.get(phase)
    if not phase_def:
        return None

    # First question of the phase — use opening
    if len(conversation) <= 1:
        return phase_def["opening"]

    # Try LLM
    llm_question = await call_llm(
        messages=conversation[-6:],  # last 6 messages for context
        system_prompt=phase_def["llm_system"],
    )

    if llm_question:
        return llm_question

    # Fallback to template
    return get_next_template_prompt(session_data)


async def analyze_answer(
    session_data: dict[str, Any],
    conversation: list[dict[str, str]],
) -> dict[str, Any]:
    """Analyze the expert's last answer for knowledge extraction."""
    phase = session_data["current_phase"]
    phase_def = PHASE_DEFINITIONS.get(phase)

    # Try LLM analysis
    analysis_prompt = f"""Analiza la última respuesta del experto en la Fase {phase} ({phase_def['name'] if phase_def else 'unknown'}).

Extrae:
1. knowledge_items: lista de afirmaciones con categoría (fact/judgment/intuition/pattern/gap) y peso (0.0-1.0)
2. concepts: conceptos clave mencionados
3. gaps: discrepancias con documentación

Responde SOLO con JSON:
{{"knowledge_items": [{{"statement": "...", "category": "fact", "weight": 0.7, "rationale": "..."}}],
  "concepts": ["..."],
  "gaps": ["..."]}}"""

    llm_analysis = await call_llm(
        messages=conversation[-4:],
        system_prompt=analysis_prompt,
        temperature=0.3,
    )

    if llm_analysis:
        try:
            return json.loads(llm_analysis)
        except json.JSONDecodeError:
            logger.warning(f"LLM returned invalid JSON: {llm_analysis[:200]}")

    # Default empty result
    return {"knowledge_items": [], "concepts": [], "gaps": []}


async def generate_summary(
    session_data: dict[str, Any],
    conversation: list[dict[str, str]],
    all_items: list[dict[str, Any]],
) -> str:
    """Generate a session summary using LLM."""
    items_summary = "\n".join(
        f"- [{item.get('category','?')}] {item.get('statement','')}"
        for item in all_items
    )

    summary_prompt = f"""Genera un resumen ejecutivo de esta sesión de captura de conocimiento.

Experto: {session_data.get('expert_name','?')}
Rol: {session_data.get('expert_role','?')}
Dominio: {session_data.get('domain','?')}

Conocimiento capturado:
{items_summary}

Resumen (máx. 3 párrafos): qué tipo de conocimiento se capturó, gaps principales,
recomendaciones para la organización."""

    llm_summary = await call_llm(
        messages=[{"role": "user", "content": summary_prompt}],
        temperature=0.5,
    )

    if llm_summary:
        return llm_summary

    return (
        f"Sesión completada con {len(all_items)} items de conocimiento "
        f"en {len(PHASE_ORDER)} fases."
    )
