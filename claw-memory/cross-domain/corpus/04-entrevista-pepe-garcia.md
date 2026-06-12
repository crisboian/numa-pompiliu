# Numa Capture — Entrevista Experto Industrial
# Experto: Pepe García, 22 años operando la K-700
# Fecha: 2026-03-15
# Protocolo NUMA Capture (4 fases, ~3.5h)

## Fase A: Mapping (30 min) — "Lo que nadie sabe que yo sé"

"La K-700 es una máquina noble pero tiene sus mañas. Lo que pone el manual y lo que hacemos en el día a día son dos mundos distintos. El manual dice 170-190 bar y 120 segundos de arranque. Pero si arrancas un lunes de enero a las 6 de la mañana con 4°C en la nave, necesitas el triple de tiempo. Si no, la bomba cavita y te cargas los retenes en tres meses. Esto no está en ningún sitio. Yo lo aprendí a base de ver dos bombas reventadas.

La junta derecha, la K7-GR-0034, es el punto débil de esta máquina. El fabricante dice 190°C máximo, pero esa junta se degrada a partir de 175°C. La diferencia es que el fabricante mide la temperatura del fluido en el depósito, no en el pistón. El pistón derecho está justo al lado del serpentín de calefacción, así que va 30-40°C más caliente que el depósito. Por eso la incidencia de 2019. Yo nunca paso de 185°C en el indicador del depósito. Con eso, la junta derecha está a unos 215°C reales y ya empieza a sufrir.

El manual dice que el aceite ISO VG 46 vale para todo el año. Mentira. En invierno necesitas VG 32, más fluido en frío. En verano el VG 46 va bien. Pero el de mantenimiento solo pide VG 46 porque es más barato comprar un solo bidón. Yo, en noviembre, vacío un 30% del depósito y lo relleno con VG 32. No es oficial. Pero la bomba me dura el doble que a mis compañeros."

## Fase B: Critical Cases (90 min)

"El peor día fue el 14 de marzo de 2019. Yo no estaba, era el turno de mañana y estaba J. Martínez. Llevaban tres turnos seguidos procesando acero de 12mm a tope de presión. El aceite se fue calentando y calentando. El termostato de seguridad estaba mal calibrado de fábrica — 200°C en vez de 180°C. Cuando el indicador marcó 193°C, la junta derecha ya estaba a más de 220°C. Se fundió, soltó aceite a presión, el aceite tocó la resistencia de la máquina de al lado... casi tenemos un incendio grave.

Lo peor no fue el fallo técnico. Lo peor fue que J. Martínez llevaba años diciendo que la junta derecha se calentaba más de lo normal. Lo comentaba en los cafés. Pero nunca se documentó. Si se hubiera escrito en algún sitio, quizá alguien habría mirado el termostato antes. Cuatro días de parada y 3.200 euros por no apuntar una cosa.

Otro caso: el chaval nuevo en 2022. Confundió la línea del aluminio 7075 con la del 6061. 185 bar en vez de 170. El supervisor lo pilló a tiempo. Pero yo me pregunto: ¿por qué la tabla de materiales es un PDF borroso colgado en la pared? Si el sistema te dijera 'Oye, para 7075 no puedes pasar de 170', el chaval no habría metido la pata. Pero los sistemas no hablan, dependemos de que el veterano esté mirando.

Y el tercer caso que me quita el sueño es qué va a pasar cuando yo me jubile. Me quedan dos años. El que venga detrás va a leer el manual y va a hacer exactamente lo que pone: 120 segundos de arranque, VG 46 todo el año, 190°C sin problema. Y en tres meses va a reventar la máquina. Porque el manual miente. No miente a propósito, pero omite todo lo que el contexto cambia."

## Fase C: Inverse Verification (60 min) — "El manual dice X, tú dices Y"

**LLM:** "El manual de la K-700 establece 170-190 bar como presión de trabajo. Tú recomiendas no pasar de 185 bar. ¿Por qué?"

**Pepe García:** "Porque a 190 bar la bomba va forzada y genera más calor. Y el calor es lo que mata la junta derecha. Entre 185 y 190 bar solo ganas un 3% de fuerza, pero generas un 15% más de calor. No compensa."

**LLM:** "El manual dice 120 segundos de arranque. ¿Por qué usas 300 en invierno?"

**Pepe García:** "El manual está escrito en Barcelona, donde en enero hace 10°C. Esta nave en Brihuega en enero está a 2°C. A 2°C, el VG 46 tiene el triple de viscosidad que a 20°C. La bomba necesita más tiempo para mover ese aceite frío sin cavitar. Si respetas los 120 segundos a 2°C, la bomba aspira en vacío durante 2-3 segundos. Cada vez que cavita, arranca micropartículas metálicas. Al cabo de 100 arranques en frío, la bomba está muerta."

**LLM:** "La NTP 1.154 dice que el termostato debe estar 20°C por debajo del punto de inflamación del aceite. Eso da 200°C. Pero en vuestra máquina lo habéis puesto a 180°C. ¿Contradice esto la norma?"

**Pepe García:** "No. La NTP te dice el máximo legal, no el óptimo de seguridad. El punto de inflamación del VG 46 es 220°C. Menos 20°C son 200°C. Pero ese es el límite para que no arda el aceite, no para que no se funda la junta. La junta se funde a 190°C reales. Si pones el termostato a 200°C, cuando salta el aceite está a 200°C y la junta ya lleva 10°C muerta. La NTP protege contra incendios, no contra averías."

## Fase D: The Unwritten (30 min) — "Lo que tu sucesor necesita saber"

"Tres cosas que no están en ningún documento y que le diría a mi sucesor el primer día:

1. **La junta derecha se cambia cada 6 meses, no cada año.** El manual dice mantenimiento anual de juntas. Pero la derecha sufre el doble. Si esperas un año, hay un 40% de probabilidades de que falle antes. Cambiarla cada 6 meses cuesta 185€. Una parada de producción cuesta 3.200€. Las matemáticas son claras.

2. **El aceite se mezcla en invierno.** 70% VG 46 + 30% VG 32 de noviembre a marzo. No es ortodoxo, ningún fabricante lo recomienda. Pero alarga la vida de la bomba un 60%. El mecánico oficial te dirá que no lo hagas. Dile que lo autorizo yo.

3. **Si el indicador de temperatura marca más de 55°C, para la producción.** No esperes a que llegue a 60°C ni a que salte la alarma. A 55°C en el depósito, la junta derecha ya está a 190°C. Es el punto donde el deterioro se acelera exponencialmente. Una hora parado para enfriar cuesta menos que cuatro días de reparación.

Y una cuarta, la más importante: **si algo te parece raro, apúntalo.** No hace falta que sea un informe formal. Una nota en un post-it, un mensaje en el grupo, lo que sea. La mayoría de las averías graves que he visto tenían señales previas que alguien notó pero nadie documentó."
