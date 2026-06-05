# Protocolo 05: Conocimiento Negativo y Anti-Patrones

**Fase E del ciclo de captura NUMA — Duración: 30 min**

## Objetivo

Capturar el conocimiento que **no está en ningún manual** pero que **salva vidas**: errores costosos, anti-patrones, condiciones de alto riesgo, y advertencias explícitas para el sucesor. Esta es la fase más crítica para seguridad industrial.

## Cuándo se aplica

Siempre que el dominio tenga consecuencias físicas (seguridad, salud, maquinaria). Opcional en dominios puramente administrativos.

## Estructura de la entrevista

### Pregunta de apertura

> "Esta es la fase más importante para la seguridad. Vamos a hablar de errores. ¿Cuál fue el error más caro que cometiste o viste cometer en tu puesto? Cuéntamelo todo: qué pasó, qué lo causó, qué consecuencias tuvo."

### Preguntas de seguimiento (4)

1. **Lo que costó aprender**: "¿Qué costó aprender? Dime algo que ahora te parece obvio pero que cuando empezaste no lo era, y te costó un disgusto aprenderlo."
2. **El novato listo**: "¿Hay cosas que haces diferente a cómo indica el manual, pero que si un novato hiciera como tú sin entender por qué, podría causar un accidente?"
3. **El error fatal**: "¿Cuál es el error que tu sucesor NO puede cometer bajo ningún concepto? El que podría costarle el puesto, la salud o peor."
4. **Patrones estacionales/situacionales**: "¿Hay algún momento del año, turno, condición meteorológica, o estado de máquina en el que los errores son más probables?"

### Técnicas de profundización

| Técnica | Pregunta guía |
|---------|--------------|
| **La cicatriz** | "Enséñame la cicatriz" — pide historias de errores con consecuencias reales |
| **El novato listo** | ¿Qué haría un novato con buenas intenciones que podría salir mal? |
| **Lo obvio mortal** | ¿Qué es obvio para ti pero letal para otros? |
| **El casi** | Cuéntame una vez que casi ocurre una catástrofe y solo tu intervención lo evitó |
| **La esquina ciega** | ¿Hay algo que todo el mundo da por hecho y no debería? |

## Formato de salida

```json
{
  "knowledge_items": [
    {
      "statement": "Nunca abrir la válvula X sin purgar antes la línea Y",
      "category": "antipattern",
      "weight": 0.9,
      "conditions": ["mantenimiento programado", "cambio de turno"],
      "phase": "E",
      "rationale": "Causó 2 incidentes en 2021-2023 por sobrepresión"
    },
    {
      "statement": "Los lunes por la mañana son el momento de más riesgo de error",
      "category": "pattern",
      "weight": 0.7,
      "conditions": ["lunes 6-8am", "post-fin de semana largo"],
      "phase": "E",
      "rationale": "Distracción post-descanso, máquinas frías"
    }
  ],
  "fatal_errors": [
    "Error que el sucesor NO puede cometer: ..."
  ],
  "seasonal_patterns": [
    "Verano: mayor probabilidad de X por calor en nave"
  ],
  "successor_warnings": [
    "Advertencia directa al sucesor: ..."
  ]
}
```

## Categorías de peso

| Categoría | Peso | Cuándo |
|-----------|------|--------|
| `antipattern` | 0.9 | Algo que parece correcto pero no lo es |
| `fatal_error` | 1.0 | Error que puede causar daño grave |
| `near_miss` | 0.8 | Casi accidente que se evitó por los pelos |
| `costly_mistake` | 0.7 | Error que costó dinero/tiempo |
| `seasonal_pattern` | 0.6 | Patrón estacional o situacional |
| `successor_warning` | 0.9 | Advertencia explícita al sucesor |

## Integración con Shadowing

Los items de Shadow Log con categoría `warning` se promocionan automáticamente a la Fase E si el experto lo confirma. Cualquier entrada shadow con tag `seguridad` o `emergencia` se marca como candidata a Fase E.

## Verificación

Después de la Fase E, el sistema debe generar 3 preguntas de verificación:

1. "¿Qué error mencionaste que podría ser el más peligroso para un sustituto?"
2. "¿En qué condiciones dijiste que los errores son más probables?"
3. " ¿Hay algún anti-patrón que quieras añadir después de repasar la lista?"

La Fase E se considera validada cuando el experto confirma que ha cubierto los errores que considera críticos.
