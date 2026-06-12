"""
NUMA Fact Extractor — Extracts atomic facts from text.
Identifies: IPs, hostnames, URLs, credentials, model names, API tokens, ports.
"""
import re
from typing import Optional


# ── Patterns for atomic facts ──────────────────────────────────
PATTERNS = [
    # IPv4 addresses with optional port
    (r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d{2,5})?)', "IP/endpoint"),
    # URLs
    (r'(https?://[^\s\)\]>,]+)', "URL"),
    # Model names (DeepSeek, GPT-4, Claude, Gemma, Llama, etc.) — strict, known models only
    (r'\b(Deep[Ss]eek\s*(?:Pro|Flash|V\d|R1|Coder)?|GPT-?\d[\w.-]*|Claude\s*[\d.]+\s*(?:Opus|Sonnet|Haiku)?|Gemma\s*[\d]+(?:\s*(?:\d+B|B))?|Llama\s*[\d.]+(?:B)?|Mistral|Mixtral|Falcon|Phi[\d-]+|Ollama|Gemini)\b', "model"),
    # Credentials (user:pass or user/pass patterns)
    (r'(?:user|pass|login|credential|token)[s]?\s*(?:[:=]|\s+is\s+)\s*([^\s,;]+)', "credential"),
    # API tokens / keys
    (r'([a-zA-Z0-9_-]{20,60})', "token_candidate"),
    # Ports with service
    (r'(?:port|puerto)\s+(\d{2,5})', "port"),
    # Hostnames in config context
    (r'(?:host|hostname|server)\s*[:=]\s*([^\s,;]+)', "hostname"),
    # File paths
    (r'(/(?:[a-zA-Z0-9._-]+/)+[a-zA-Z0-9._-]+)', "filepath"),
    # Chat IDs (negative numbers for Telegram)
    (r'(?:chat[_\s]?id|grupo)[^\d]*(-?\d{8,15})', "chat_id"),
    # Email addresses
    (r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', "email"),
    # Model size / dimensions
    (r'(\d{2,4}\s*(?:dimensions?|dim|parámetros?|params?|B|M))', "model_spec"),
]


def extract_facts(text: str, source: str = "") -> list[dict]:
    """Extract atomic fact statements from text.

    Returns list of {statement, tier, source, category}
    """
    facts = []
    seen = set()

    for pattern, category in PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = match.group(1).strip()
            if len(value) < 3:
                continue
            if value in seen:
                continue
            seen.add(value)

            # Build context (surrounding text for disambiguation)
            start = max(0, match.start() - 80)
            end = min(len(text), match.end() + 80)
            context = text[start:end].strip()
            # Clean context
            context = re.sub(r'\s+', ' ', context)

            facts.append({
                "statement": f"{value} — {context[:200]}",
                "tier": "facts",
                "source": source,
                "category": category,
            })

    return facts


def extract_facts_only(text: str, source: str = "") -> list[dict]:
    """Extract just the values without full context for cleaner statements."""
    facts = []
    seen = set()

    for pattern, category in PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = match.group(1).strip()
            if len(value) < 3 or len(value) > 120:
                continue
            if value in seen:
                continue
            seen.add(value)

            # Skip obvious false positives
            if re.match(r'^\d+$', value) and int(value) < 100:
                continue  # Skip bare small numbers
            if len(value) > 80 and category == "token_candidate":
                continue  # Skip long random strings without context

            facts.append({
                "value": value,
                "category": category,
                "source": source,
            })

    return facts


if __name__ == "__main__":
    # Test
    test = """
    Proxmox host: 192.168.99.1, API token: root@pam!claw / fa468e4d-544e-4cd2-abca-66d992323051
    Hermes: 192.168.99.12, SSH port 22
    Windows .14: 192.168.99.14, user riav92 / 11992
    Model: DeepSeek Pro with fallback to Gemma 4 on LM Studio at http://192.168.99.14:1234
    Telegram group chat: -5259791635
    Claw gateway port: 18789
    Embeddings: all-MiniLM-L6-v2, 384 dimensions
    """
    for f in extract_facts_only(test, "test"):
        print(f"[{f['category']:18s}] {f['value']}")
