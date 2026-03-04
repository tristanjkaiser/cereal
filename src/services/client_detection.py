"""Client detection from meeting title and attendee data.

Extracted from mcp_server/server.py and scripts/auto_archive.py to
eliminate duplication. Both consumers now import from here.
"""
import os
import re
from typing import List, Optional


def detect_client_from_meeting(
    title: str,
    attendees: List[dict],
    known_clients: List[str],
    aliases: Optional[dict] = None,
    internal_domain: str = None,
) -> Optional[str]:
    """
    Detect client from meeting title and attendee data.

    Detection priority:
    0. Alias match (highest priority - user-defined mappings)
    1. Known client name appears in title
    2. Title patterns like "Client x Goji", "Client:", "Record Client"
    3. External attendee company name (if only one external company)

    Args:
        title: Meeting title
        attendees: List of attendee dicts with 'email' and 'company' keys
        known_clients: List of known client names from database
        aliases: Dict mapping alias (lowercase) -> canonical client name
        internal_domain: Email domain treated as internal (default from INTERNAL_DOMAIN env)

    Returns:
        Client name if detected, None otherwise
    """
    if internal_domain is None:
        internal_domain = os.getenv("INTERNAL_DOMAIN", "gojilabs.com")

    if not title:
        return None
    title_lower = title.lower()

    # 0. Check aliases FIRST (highest priority - user-defined mappings)
    if aliases:
        for alias, canonical in aliases.items():
            if alias in title_lower:
                return canonical

    # 1. Known client match (case-insensitive)
    for client in known_clients:
        if client.lower() in title_lower:
            return client

    # 2. Title pattern extraction
    patterns = [
        r'^([A-Za-z0-9]+)\s+x\s+Goji',       # "NGynS x Goji"
        r'^([A-Za-z0-9]+):',                  # "GS1: ..."
        r'^Record\s+([A-Za-z0-9]+)',          # "Record NB44 ..."
    ]
    for pattern in patterns:
        match = re.match(pattern, title, re.IGNORECASE)
        if match:
            return match.group(1)

    # 3. External attendee detection
    external_companies = set()
    for att in attendees:
        email = att.get('email', '')
        if email and not email.endswith(f'@{internal_domain}'):
            company = att.get('company')
            if company and company.lower() not in ['unknown', 'goji labs', 'gojilabs']:
                external_companies.add(company)

    if len(external_companies) == 1:
        return external_companies.pop()

    return None
