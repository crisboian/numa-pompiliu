"""
NUMA Capture Web — Stripe Payment Integration.

Provides:
- Product definitions (report_basic, report_pro, report_enterprise)
- Stripe product/price auto-creation on startup
- POST /api/stripe/create-checkout-session — creates a Stripe Checkout Session
- POST /api/stripe/webhook — processes Stripe events (checkout.session.completed)
- check_report_access() — verifies a session ID has been paid for

Environment variables:
- STRIPE_SECRET_KEY        (required) — Stripe API secret key
- STRIPE_WEBHOOK_SECRET    (required) — Stripe webhook signing secret
- NUMA_BASE_URL            (required) — base URL for redirect after checkout
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import stripe
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("numa-stripe")

# ─── Configuration from environment ─────────────────────────────────────────

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
NUMA_BASE_URL = os.environ.get("NUMA_BASE_URL", "http://localhost:8765")

# ─── Product definitions ────────────────────────────────────────────────────
# Defined in code (not in Stripe dashboard). Created via Stripe API on startup.
# Prices in EUR cents (stripe expects integer cents).


@dataclass
class ProductDef:
    """Definition of a Stripe product and its price."""

    key: str
    name: str
    description: str
    price_eur_cents: int  # price in EUR cents (e.g. 900 = €9.00)
    # Stripe IDs populated after API creation
    stripe_product_id: str = ""
    stripe_price_id: str = ""


PRODUCTS: dict[str, ProductDef] = {
    "report_basic": ProductDef(
        key="report_basic",
        name="Informe Básico",
        description="Informe de 1 dominio — análisis completo de una sesión NUMA",
        price_eur_cents=0,  # Free
    ),
    "report_pro": ProductDef(
        key="report_pro",
        name="Informe Pro",
        description="Informe multi-dominio — comparativa entre varios dominios",
        price_eur_cents=1900,  # €19.00
    ),
    "report_enterprise": ProductDef(
        key="report_enterprise",
        name="Informe Enterprise",
        description="Informe completo con grafo de conocimiento industrial",
        price_eur_cents=4900,  # €49.00
    ),
}


# ─── Purchase store (persistent JSON file) ──────────────────────────────────
# Stores mapping: session_id -> { product_key, stripe_session_id, amount, paid_at }
# This avoids modifying server.py or database.py for now.

PURCHASE_DB_PATH = Path(os.environ.get("NUMA_DATA_DIR", "/opt/numa-cloud/data")) / "stripe_purchases.json"


def _load_purchases() -> dict[str, dict[str, Any]]:
    """Load purchases from JSON file. Returns dict[session_id] -> purchase info."""
    if not PURCHASE_DB_PATH.exists():
        return {}
    try:
        with open(PURCHASE_DB_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load purchases DB: %s", exc)
        return {}


def _save_purchases(purchases: dict[str, dict[str, Any]]) -> None:
    """Save purchases to JSON file atomically."""
    PURCHASE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PURCHASE_DB_PATH.with_suffix(".tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(purchases, f, indent=2)
        tmp.rename(PURCHASE_DB_PATH)
    except OSError as exc:
        logger.error("Failed to save purchases DB: %s", exc)


def _record_purchase(
    session_id: str,
    product_key: str,
    stripe_session_id: str,
    amount_cents: int,
) -> None:
    """Record a completed purchase in the JSON store."""
    purchases = _load_purchases()
    purchases[session_id] = {
        "product_key": product_key,
        "stripe_session_id": stripe_session_id,
        "amount_cents": amount_cents,
        "paid_at": time.time(),
    }
    _save_purchases(purchases)
    logger.info(
        "Purchase recorded: session=%s product=%s amount=%d",
        session_id,
        product_key,
        amount_cents,
    )


# ─── Stripe product initialisation ──────────────────────────────────────────


def init_stripe_products() -> dict[str, ProductDef]:
    """Create or retrieve Stripe products and prices.

    Called once at startup. Looks up existing products by metadata[key]=product_key,
    or creates them via the Stripe API. Populates PRODUCTS with live IDs.

    Returns PRODUCTS dict (with stripe_product_id and stripe_price_id populated).
    """
    stripe.api_key = STRIPE_SECRET_KEY

    for product_def in PRODUCTS.values():
        _ensure_stripe_product(product_def)

    logger.info(
        "Stripe products ready: %s",
        {k: f"{v.stripe_product_id}/{v.stripe_price_id}" for k, v in PRODUCTS.items()},
    )
    return PRODUCTS


def _ensure_stripe_product(product_def: ProductDef) -> None:
    """Create or retrieve a single Stripe product+price by metadata key."""
    try:
        # Try to find existing product by our metadata key
        existing = stripe.Product.search(
            query=f"metadata['numa_product_key']:'{product_def.key}'",
            limit=1,
        )
        if existing.data:
            prod = existing.data[0]
            product_def.stripe_product_id = prod.id
            logger.info("Found existing Stripe product: %s (%s)", product_def.key, prod.id)

            # Find the active price for this product
            prices = stripe.Price.list(
                product=prod.id,
                active=True,
                limit=1,
            )
            if prices.data:
                product_def.stripe_price_id = prices.data[0].id
                logger.info(
                    "Found existing price: %s (%s)", product_def.key, product_def.stripe_price_id
                )
                return

        # Product doesn't exist — create it
        prod = stripe.Product.create(
            name=product_def.name,
            description=product_def.description,
            metadata={"numa_product_key": product_def.key},
        )
        product_def.stripe_product_id = prod.id
        logger.info("Created Stripe product: %s (%s)", product_def.key, prod.id)

        # Create the price
        price = stripe.Price.create(
            product=prod.id,
            unit_amount=product_def.price_eur_cents,
            currency="eur",
            metadata={"numa_product_key": product_def.key},
        )
        product_def.stripe_price_id = price.id
        logger.info("Created Stripe price: %s (%s)", product_def.key, price.id)

    except stripe.error.StripeError as exc:
        logger.error("Stripe API error for product '%s': %s", product_def.key, exc)
        raise


# ─── Pydantic request models ────────────────────────────────────────────────


class CreateCheckoutRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=36)
    product_key: str = Field(..., min_length=1, max_length=32)


# ─── FastAPI Router ─────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/stripe", tags=["stripe"])


@router.post("/create-checkout-session", status_code=201)
async def create_checkout_session(
    req: CreateCheckoutRequest,
):
    """Create a Stripe Checkout Session for a product (report).

    The user specifies a session_id (NUMA interview session) and a product_key
    (report_basic, report_pro, report_enterprise). Returns a Stripe Checkout
    Session URL for redirect.

    Body:
        {"session_id": "...", "product_key": "report_basic"}

    Returns:
        {"url": "https://checkout.stripe.com/...", "session_id": "cs_..."}
    """
    stripe.api_key = STRIPE_SECRET_KEY

    # Validate product
    product_def = PRODUCTS.get(req.product_key)
    if not product_def:
        valid = list(PRODUCTS.keys())
        raise HTTPException(
            status_code=400,
            detail=f"Invalid product_key. Must be one of: {valid}",
        )

    if not product_def.stripe_price_id and product_def.price_eur_cents > 0:
        raise HTTPException(
            status_code=500,
            detail="Stripe product not initialized. Call init_stripe_products() first.",
        )

    # Build the success / cancel URLs
    success_url = f"{NUMA_BASE_URL}/report/{req.session_id}"
    cancel_url = f"{NUMA_BASE_URL}/pricing"

    # Free product — skip Stripe entirely
    if product_def.price_eur_cents == 0:
        _record_purchase(
            session_id=req.session_id,
            product_key=req.product_key,
            stripe_session_id="free",
            amount_cents=0,
        )
        return {
            "url": success_url,
            "session_id": "free",
            "session_status": "complete",
        }

    try:
        checkout_session = stripe.checkout.Session.create(
            line_items=[
                {
                    "price": product_def.stripe_price_id,
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "session_id": req.session_id,
                "product_key": req.product_key,
            },
        )
    except stripe.error.StripeError as exc:
        logger.error("Stripe checkout session creation failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Stripe API error: {exc.user_message or 'Unknown error'}",
        )

    logger.info(
        "Checkout session created: %s for session=%s product=%s",
        checkout_session.id,
        req.session_id,
        req.product_key,
    )

    return {
        "url": checkout_session.url,
        "session_id": checkout_session.id,
        "session_status": checkout_session.status,
    }


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="stripe-signature"),
):
    """Handle Stripe webhook events.

    Mainly handles:
    - checkout.session.completed — records the purchase, grants access

    Stripe sends the raw body with a stripe-signature header.
    We verify it using STRIPE_WEBHOOK_SECRET.
    """
    stripe.api_key = STRIPE_SECRET_KEY

    # Read raw body
    payload = await request.body()

    # Refuse to process anything without a webhook secret. Accepting unsigned
    # events would let anyone forge "checkout.session.completed" and grant
    # themselves paid access. 503 because the webhook is misconfigured, not
    # because the caller did anything wrong.
    if not STRIPE_WEBHOOK_SECRET:
        logger.error("Stripe webhook called but STRIPE_WEBHOOK_SECRET is not configured")
        raise HTTPException(
            status_code=503,
            detail="Webhook signing not configured",
        )

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError as exc:
        logger.warning("Stripe webhook signature verification failed: %s", exc)
        raise HTTPException(status_code=403, detail="Invalid signature")
    except ValueError as exc:
        logger.warning("Stripe webhook invalid payload: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid payload")

    event_type = event.get("type") if hasattr(event, "get") else event.type
    logger.info("Stripe webhook received: %s", event_type)

    # ── Handle checkout.session.completed ──
    if event_type == "checkout.session.completed":
        session_obj = event.data.object

        # Extract metadata
        metadata = session_obj.get("metadata", {}) if hasattr(session_obj, "get") else (session_obj.metadata or {})
        session_id = metadata.get("session_id", "")
        product_key = metadata.get("product_key", "")

        if not session_id or not product_key:
            logger.warning(
                "checkout.session.completed missing metadata: session_id=%s product_key=%s",
                session_id,
                product_key,
            )
            return {"status": "received", "note": "missing metadata"}

        amount_cents = session_obj.get("amount_total", 0) if hasattr(session_obj, "get") else (session_obj.amount_total or 0)
        stripe_session_id = session_obj.get("id", "") if hasattr(session_obj, "get") else session_obj.id

        # Record the purchase
        _record_purchase(
            session_id=session_id,
            product_key=product_key,
            stripe_session_id=stripe_session_id,
            amount_cents=amount_cents,
        )

        logger.info(
            "Purchase completed: session=%s product=%s amount=%d cents",
            session_id,
            product_key,
            amount_cents,
        )

    # ── Handle other events (acknowledge receipt) ──
    return {"status": "received", "event": event_type}


# ─── Access control ─────────────────────────────────────────────────────────


def check_report_access(session_id: str) -> dict[str, Any] | None:
    """Check if a session/report has been paid for.

    Args:
        session_id: The NUMA session ID to check.

    Returns:
        Purchase info dict if access is granted, or None if not found/not paid.
        The dict contains: product_key, amount_cents, paid_at
    """
    purchases = _load_purchases()
    purchase = purchases.get(session_id)
    if purchase is None:
        return None
    return {
        "product_key": purchase["product_key"],
        "amount_cents": purchase["amount_cents"],
        "paid_at": purchase["paid_at"],
    }


# ─── Convenience helper for server.py integration ──────────────────────────


def setup_stripe(app: Any) -> None:
    """Convenience function: initialise Stripe products and mount the router."""
    if not os.environ.get("STRIPE_SECRET_KEY"):
        logger.warning("STRIPE_SECRET_KEY not set -- Stripe integration disabled")
        return
    try:
        init_stripe_products()
        app.include_router(router)
        logger.info("Stripe integration mounted on /api/stripe/*")
    except Exception as e:
        logger.warning("Stripe init failed: %s -- Stripe integration disabled", e)
