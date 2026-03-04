#!/usr/bin/env python3
"""
Auto-archive Granola meetings to PostgreSQL.

Runs on a schedule via launchd. Archives meetings in a time window:
- Skip meetings newer than SETTLE_HOURS (likely still in progress)
- Skip meetings older than FRESHNESS_HOURS (already finalized)
- Upsert everything in between (self-healing via ON CONFLICT DO UPDATE)

Usage:
    python scripts/auto_archive.py              # Run with defaults
    python scripts/auto_archive.py --dry-run    # Preview without writing
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.database import DatabaseManager
from src.granola_client import GranolaClient
from src.services.client_detection import detect_client_from_meeting

# Config
SETTLE_HOURS = float(os.getenv("AUTO_ARCHIVE_SETTLE_HOURS", "2"))
FRESHNESS_HOURS = float(os.getenv("AUTO_ARCHIVE_FRESHNESS_HOURS", "3"))
INTERNAL_DOMAIN = os.getenv("INTERNAL_DOMAIN", "gojilabs.com")

# Logging
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(str(LOG_DIR / "auto_archive.log")),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("auto_archive")



def in_archive_window(doc: dict, settle_hours: float, freshness_hours: float) -> bool:
    """Check if a document's created_at falls within the archive window."""
    created_at_str = doc.get('created_at') or doc.get('createdAt')
    if not created_at_str:
        return False

    try:
        created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False

    now = datetime.now(timezone.utc)
    settle_cutoff = now - timedelta(hours=settle_hours)
    freshness_cutoff = now - timedelta(hours=freshness_hours)

    return freshness_cutoff <= created_at <= settle_cutoff


def auto_archive(dry_run: bool = False, limit: int = 50,
                 settle_hours: float = SETTLE_HOURS,
                 freshness_hours: float = FRESHNESS_HOURS):
    """Main auto-archive routine."""
    start = time.time()

    logger.info(f"Auto-archive started (settle={settle_hours}h, freshness={freshness_hours}h, dry_run={dry_run})")

    # Init clients
    db = DatabaseManager(os.getenv("DATABASE_URL"))
    granola = GranolaClient()

    # Fetch state for client detection
    known_clients = db.get_client_names()
    aliases = db.get_client_aliases()
    logger.info(f"Loaded {len(known_clients)} clients, {len(aliases)} aliases")

    # Fetch documents from Granola
    documents = granola.get_documents(limit=limit)
    logger.info(f"Fetched {len(documents)} documents from Granola")

    # Filter to archive window
    to_process = []
    skipped_too_new = 0
    skipped_too_old = 0

    for doc in documents:
        doc_id = doc.get('id') or doc.get('document_id')
        if not doc_id:
            continue

        if in_archive_window(doc, settle_hours, freshness_hours):
            to_process.append(doc)
        else:
            # Determine why it was skipped for logging
            created_at_str = doc.get('created_at') or doc.get('createdAt')
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    age_hours = (now - created_at).total_seconds() / 3600
                    if age_hours < settle_hours:
                        skipped_too_new += 1
                    else:
                        skipped_too_old += 1
                except (ValueError, TypeError):
                    skipped_too_old += 1

    logger.info(f"Archive window: {len(to_process)} to process, "
                f"{skipped_too_new} too new, {skipped_too_old} too old")

    if not to_process:
        logger.info("Nothing to archive")
        return

    if dry_run:
        for doc in to_process:
            title = doc.get('title') or 'Untitled'
            logger.info(f"  [dry-run] Would archive: {title[:60]}")
        return

    # Archive each document
    archived = 0
    errors = 0

    for doc in to_process:
        doc_id = doc.get('id') or doc.get('document_id')
        title = doc.get('title') or 'Untitled'
        meeting_date = doc.get('created_at') or doc.get('createdAt')

        try:
            content = granola.get_document_content_parts(doc, debug=False)
            attendees = granola.get_document_attendees(doc)

            detected_client = detect_client_from_meeting(
                title=title,
                attendees=attendees,
                known_clients=known_clients,
                aliases=aliases,
                internal_domain=INTERNAL_DOMAIN
            )

            client_id = None
            if detected_client:
                client_id = db.get_or_create_client(detected_client)
                if detected_client not in known_clients:
                    known_clients.append(detected_client)

            db.archive_meeting(
                granola_document_id=doc_id,
                title=title,
                meeting_date=meeting_date,
                transcript=content.get('transcript'),
                enhanced_notes=content.get('enhanced_notes'),
                manual_notes=content.get('manual_notes'),
                combined_markdown=content.get('combined_markdown'),
                client_id=client_id
            )

            archived += 1
            client_note = f" -> {detected_client}" if detected_client else ""
            logger.info(f"  Archived: {title[:60]}{client_note}")

        except Exception as e:
            errors += 1
            logger.error(f"  Error archiving '{title[:40]}': {e}")

    elapsed = round(time.time() - start, 1)
    logger.info(f"Auto-archive complete: {archived} archived, {errors} errors ({elapsed}s)")


def main():
    parser = argparse.ArgumentParser(description="Auto-archive Granola meetings")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing to database")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max documents to fetch from Granola (default: 50)")
    parser.add_argument("--settle-hours", type=float, default=None,
                        help=f"Settling period in hours (default: {SETTLE_HOURS})")
    parser.add_argument("--freshness-hours", type=float, default=None,
                        help=f"Freshness cap in hours (default: {FRESHNESS_HOURS})")
    args = parser.parse_args()

    settle = args.settle_hours if args.settle_hours is not None else SETTLE_HOURS
    freshness = args.freshness_hours if args.freshness_hours is not None else FRESHNESS_HOURS

    try:
        auto_archive(
            dry_run=args.dry_run,
            limit=args.limit,
            settle_hours=settle,
            freshness_hours=freshness
        )
    except FileNotFoundError as e:
        logger.error(f"Granola credentials not found: {e}")
        logger.error("Make sure Granola is installed and you're logged in.")
        sys.exit(1)
    except ValueError as e:
        if "DATABASE_URL" in str(e):
            logger.error("DATABASE_URL not set. Check your .env file.")
        else:
            logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
