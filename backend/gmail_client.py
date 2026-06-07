"""
Gmail API client for NUMA Capture Web.

Provides functions to create Gmail drafts, manage labels, save knowledge
items as structured email drafts, and search Gmail for later RAG retrieval.

Uses google-auth-oauthlib for token management and google-api-python-client
for the Gmail API. Tokens are passed as dicts with access_token, refresh_token,
and expiry fields.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Default sender: if GMAIL_SENDER is not set, we will use the authenticated
# user's email address retrieved from the Gmail API profile.
_GMAIL_SENDER: str | None = None


def _get_gmail_sender() -> str | None:
    """Return the configured GMAIL_SENDER env var, or None."""
    return os.environ.get("GMAIL_SENDER") or None


def _build_credentials(token_info: dict[str, Any]) -> Credentials:
    """Build google.oauth2.Credentials from a token info dict.

    Args:
        token_info: Dict with keys ``access_token``, ``refresh_token``,
            and ``expiry`` (ISO-8601 string or datetime-aware object).

    Returns:
        A ``Credentials`` object ready for API calls.
    """
    expiry = token_info.get("expiry")
    if isinstance(expiry, str):
        from datetime import datetime as dt

        try:
            expiry = dt.fromisoformat(expiry)
        except (ValueError, TypeError):
            expiry = None

    creds = Credentials(
        token=token_info.get("access_token"),
        refresh_token=token_info.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=token_info.get("client_id", ""),
        client_secret=token_info.get("client_secret", ""),
        expiry=expiry,
    )

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleRequest())
        except Exception as exc:
            logger.warning("Token refresh failed: %s", exc)

    return creds


def _get_service(credentials: Credentials):
    """Build and return a Gmail API service client."""
    return build("gmail", "v1", credentials=credentials)


def _get_authenticated_email(credentials: Credentials) -> str:
    """Retrieve the authenticated user's email from the Gmail API profile.

    Falls back to GMAIL_SENDER env var if set, otherwise raises.
    """
    env_sender = _get_gmail_sender()
    if env_sender:
        return env_sender

    try:
        service = _get_service(credentials)
        profile = service.users().getProfile(userId="me").execute()
        return profile["emailAddress"]
    except HttpError as exc:
        logger.error("Failed to get profile: %s", exc)
        raise RuntimeError(
            "Could not determine sender email. Set GMAIL_SENDER env var."
        ) from exc


# Strips CR / LF (and other control chars that could split headers) per RFC 5322.
# Prevents header injection: an attacker controlling subject/to/sender cannot
# inject extra Bcc:, To:, or body content via embedded newlines.
_HEADER_FORBIDDEN = re.compile(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")


def _sanitize_header(value: str) -> str:
    """Strip CRLF and other control chars from a header value."""
    if value is None:
        return ""
    return _HEADER_FORBIDDEN.sub(" ", str(value)).strip()


def _build_message(
    to_email: str,
    subject: str,
    body: str,
    sender: str,
) -> dict[str, Any]:
    """Build a RFC 2822 message dict for the Gmail API.

    Args:
        to_email: Recipient email address.
        subject: Email subject line.
        body: Plain-text email body.
        sender: Sender email address.

    Returns:
        A dict with a ``raw`` key containing the base64url-encoded message.
    """
    import base64

    safe_sender = _sanitize_header(sender)
    safe_to = _sanitize_header(to_email)
    safe_subject = _sanitize_header(subject)

    message_lines = [
        f"From: {safe_sender}",
        f"To: {safe_to}",
        f"Subject: {safe_subject}",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=UTF-8",
        "Content-Transfer-Encoding: base64",
        "",
        body,
    ]
    raw_message = "\n".join(message_lines)
    encoded = base64.urlsafe_b64encode(raw_message.encode("utf-8")).decode("utf-8")
    return {"raw": encoded}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_gmail_draft(
    token_info: dict[str, Any],
    to_email: str,
    subject: str,
    body: str,
) -> dict[str, Any]:
    """Create a Gmail draft via the Gmail API.

    Args:
        token_info: Token dict ``{access_token, refresh_token, expiry}``.
        to_email: Recipient email address.
        subject: Email subject line.
        body: Plain-text email body.

    Returns:
        The Gmail API ``Draft`` resource dict (includes ``id`` and ``message``).

    Raises:
        RuntimeError: On API or authentication failure.
    """
    creds = _build_credentials(token_info)
    sender = _get_authenticated_email(creds)
    message = _build_message(to_email, subject, body, sender)

    try:
        service = _get_service(creds)
        draft = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": message})
            .execute()
        )
        logger.info(
            "Draft created (id=%s) for %s with subject '%s'",
            draft.get("id"),
            to_email,
            subject,
        )
        return draft
    except HttpError as exc:
        logger.error("Gmail API error creating draft: %s", exc)
        raise RuntimeError(f"Failed to create Gmail draft: {exc}") from exc


def create_or_get_label(
    token_info: dict[str, Any],
    label_name: str,
) -> dict[str, Any]:
    """Create a Gmail label or return it if it already exists.

    Handles nested label names like ``NUMA/Capture`` — Gmail stores these
    as a single label with the full path as its name.

    Args:
        token_info: Token dict ``{access_token, refresh_token, expiry}``.
        label_name: Label name, e.g. ``NUMA/Capture`` or ``NUMA/fact``.

    Returns:
        The Gmail API ``Label`` resource dict (includes ``id`` and ``name``).

    Raises:
        RuntimeError: On API or authentication failure.
    """
    creds = _build_credentials(token_info)

    try:
        service = _get_service(creds)
        # List existing labels
        labels_result = service.users().labels().list(userId="me").execute()
        existing_labels = labels_result.get("labels", [])

        # Check if label already exists (case-sensitive match on name)
        for label in existing_labels:
            if label.get("name") == label_name:
                logger.info("Label '%s' already exists (id=%s)", label_name, label["id"])
                return label

        # Create the label
        label_body = {
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        created = (
            service.users().labels().create(userId="me", body=label_body).execute()
        )
        logger.info("Label '%s' created (id=%s)", label_name, created["id"])
        return created
    except HttpError as exc:
        logger.error("Gmail API error with label '%s': %s", label_name, exc)
        raise RuntimeError(f"Failed to create/get label '{label_name}': {exc}") from exc


def save_knowledge_as_draft(
    token_info: dict[str, Any],
    knowledge_item: dict[str, Any],
    session_id: str,
) -> dict[str, Any]:
    """Save a knowledge item as a structured Gmail draft with labels.

    The draft is formatted with full metadata in the body and auto-labeled
    with ``NUMA/{session_id[:8]}`` and ``NUMA/{category}`` labels.

    Args:
        token_info: Token dict ``{access_token, refresh_token, expiry}``.
        knowledge_item: Dict with keys ``id``, ``statement``, ``category``
            (``fact``/``judgment``/``intuition``), ``weight``, ``phase``,
            ``rationale``, and ``conditions``.
        session_id: Session identifier used for the ``NUMA/{session_id[:8]}``
            label. Only the first 8 characters are used.

    Returns:
        The Gmail API ``Draft`` resource dict with ``labels`` in ``message``.

    Raises:
        ValueError: If ``knowledge_item`` is missing required keys.
        RuntimeError: On API or authentication failure.
    """
    # Validate required fields
    required_keys = {"id", "statement", "category"}
    missing = required_keys - set(knowledge_item.keys())
    if missing:
        raise ValueError(
            f"knowledge_item missing required keys: {', '.join(sorted(missing))}"
        )

    creds = _build_credentials(token_info)
    sender = _get_authenticated_email(creds)

    # Extract fields with defaults
    item_id: str = knowledge_item["id"]
    statement: str = knowledge_item["statement"]
    category: str = knowledge_item.get("category", "unknown")
    weight: float = knowledge_item.get("weight", 0.0)
    phase: str = knowledge_item.get("phase", "")
    rationale: str = knowledge_item.get("rationale", "")
    conditions: list[str] = knowledge_item.get("conditions", [])

    # Truncated statement for subject line
    short_statement = statement[:57] + "..." if len(statement) > 60 else statement

    # Build email body with structured metadata
    body_parts = [
        f"NUMA Knowledge Capture — {category.upper()}",
        "=" * 50,
        "",
        f"Statement: {statement}",
        "",
        "--- Metadata ---",
        f"ID:       {item_id}",
        f"Category: {category}",
        f"Weight:   {weight}",
        f"Phase:    {phase}",
        f"Session:  {session_id}",
        f"Captured: {datetime.now(timezone.utc).isoformat()}",
    ]

    if rationale:
        body_parts.extend(["", f"Rationale: {rationale}"])

    if conditions:
        body_parts.extend(["", "Conditions:"])
        for idx, cond in enumerate(conditions, 1):
            body_parts.append(f"  {idx}. {cond}")

    body = "\n".join(body_parts)

    subject = f"NUMA Knowledge: {category} - {short_statement}"

    # Build the draft message
    message = _build_message(sender, subject, body, sender)

    # Ensure labels exist and add them to the draft
    session_label_name = f"NUMA/{session_id[:8]}"
    category_label_name = f"NUMA/{category}"

    try:
        session_label = create_or_get_label(token_info, session_label_name)
        category_label = create_or_get_label(token_info, category_label_name)

        # Add label IDs to the message so the draft is pre-labeled
        label_ids = [session_label["id"], category_label["id"]]
        message["labelIds"] = label_ids

        service = _get_service(creds)
        draft = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": message})
            .execute()
        )

        # Apply labels to the draft message after creation
        # (drafts can have labels applied to their underlying messages)
        message_id = draft["message"]["id"]
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": label_ids, "removeLabelIds": []},
        ).execute()

        logger.info(
            "Knowledge draft created (id=%s) for category '%s', session '%s'",
            draft.get("id"),
            category,
            session_id,
        )
        return draft

    except HttpError as exc:
        logger.error("Gmail API error saving knowledge draft: %s", exc)
        raise RuntimeError(f"Failed to save knowledge draft: {exc}") from exc


def search_gmail(
    token_info: dict[str, Any],
    query: str,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Search Gmail messages using Gmail query syntax.

    Useful for RAG (Retrieval-Augmented Generation) workflows — returns
    message metadata and snippet for further processing.

    Args:
        token_info: Token dict ``{access_token, refresh_token, expiry}``.
        query: Gmail search query string (see Gmail search operators
            documentation). Example: ``subject:"NUMA Knowledge"``.
        max_results: Maximum number of messages to return (default 50,
            max 500).

    Returns:
        List of message dicts, each containing ``id``, ``threadId``,
        ``snippet``, and ``labelIds``.

    Raises:
        RuntimeError: On API or authentication failure.
    """
    creds = _build_credentials(token_info)

    try:
        service = _get_service(creds)
        results = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=min(max_results, 500))
            .execute()
        )

        messages: list[dict[str, Any]] = []
        raw_messages = results.get("messages", [])

        # Fetch snippet and labels for each message
        for msg_meta in raw_messages:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_meta["id"], format="metadata")
                .execute()
            )
            messages.append(
                {
                    "id": msg["id"],
                    "threadId": msg.get("threadId"),
                    "snippet": msg.get("snippet", ""),
                    "labelIds": msg.get("labelIds", []),
                    "internalDate": msg.get("internalDate"),
                }
            )

        logger.info(
            "Gmail search returned %d results for query: %s",
            len(messages),
            query,
        )
        return messages

    except HttpError as exc:
        logger.error("Gmail API error searching: %s", exc)
        raise RuntimeError(f"Failed to search Gmail: {exc}") from exc


def get_message_body(
    token_info: dict[str, Any],
    message_id: str,
) -> str:
    """Retrieve the full plain-text body of a Gmail message by ID.

    Args:
        token_info: Token dict ``{access_token, refresh_token, expiry}``.
        message_id: The Gmail message ID to fetch.

    Returns:
        The decoded plain-text body of the message.

    Raises:
        RuntimeError: On API or authentication failure.
    """
    import base64

    creds = _build_credentials(token_info)

    try:
        service = _get_service(creds)
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

        # Extract body parts from the message payload
        payload = msg.get("payload", {})
        parts = payload.get("parts", [payload])  # fallback: treat payload as sole part

        body_text = ""
        for part in parts:
            mime_type = part.get("mimeType", "")
            body_data = part.get("body", {}).get("data", "")
            if mime_type == "text/plain" and body_data:
                decoded = base64.urlsafe_b64decode(
                    body_data.encode("utf-8")
                ).decode("utf-8")
                body_text += decoded

        return body_text

    except HttpError as exc:
        logger.error("Gmail API error fetching message %s: %s", message_id, exc)
        raise RuntimeError(f"Failed to fetch message body: {exc}") from exc
