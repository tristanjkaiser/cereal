"""AI-powered todo extraction from meeting transcripts.

Calls Claude (Haiku by default) to extract action items from transcripts
and detect completed todos. Opt-in via CEREAL_TODO_EXTRACTION=1.
"""
import json
import logging
import os
import re

from src.services.todo_service import TodoService

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You extract action items from meeting transcripts for a product/project manager who runs client engagements at an agency. Return JSON only.

The user is a PM — they need to track items THEY personally need to drive, not tasks owned by developers, designers, or other team members.

Output format:
{
  "new_todos": [
    {"title": "...", "description": "...", "priority": 3, "category": "...", "assigned_to": "us|them|unclear"}
  ],
  "completed_todos": [
    {"search": "title substring matching an existing todo", "evidence": "brief reason"}
  ]
}

EXTRACT these kinds of items:
- Decisions the PM needs to make, drive, or get sign-off on
- Client deliverables, approvals, and deadlines the PM owns (e.g. "Send SOW", "Get approval on estimate")
- Commitments made to the client that the PM must ensure happen
- Blockers the PM needs to escalate or unblock
- Strategic follow-ups (e.g. "Schedule kickoff", "Align on scope", "Share timeline")
- Items the client owes back ("them") that the PM needs to track

DO NOT extract:
- Developer tasks (set up repo, fix bug, implement feature, deploy, write tests)
- Design tasks (create wireframes, update mockups, build component library, explore UI)
- Internal team process items (standups, code reviews, PR approvals, sprint ceremonies)
- Routine coordination between team members that doesn't need PM attention
- Vague discussion topics that aren't concrete next steps

Rules:
- title: imperative, concise (e.g. "Send revised estimate to client")
- priority: 1=Urgent, 2=High, 3=Normal (default), 4=Low
- category: decision | deliverable | follow-up | billing | planning | blocker | review | other
- assigned_to: "us" = PM/our agency, "them" = the client/external party, "unclear" = ambiguous
- For completed_todos, only include items explicitly described as finished/done/shipped
- Be highly conservative: when in doubt, skip it. Fewer high-signal items are better than many low-level ones. Empty arrays are fine."""

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


class TodoExtractionService:
    def __init__(self, db, api_key=None, model=None):
        self.db = db
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._model = model or os.getenv("CEREAL_EXTRACTION_MODEL", DEFAULT_MODEL)
        self._client = None

    @staticmethod
    def is_enabled() -> bool:
        return os.getenv("CEREAL_TODO_EXTRACTION", "").lower() in ("1", "true", "yes")

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def extract_todos_from_meeting(
        self, meeting_id, client_id, title,
        enhanced_notes, transcript, force=False
    ) -> dict:
        """Extract todos from a meeting transcript via LLM.

        Returns:
            {"new_count": int, "completed_count": int, "skipped": bool, "error": str|None}
        """
        result = {"new_count": 0, "completed_count": 0, "skipped": False, "error": None}

        try:
            # Dedup check
            if not force and self.db.is_todos_extracted(meeting_id):
                result["skipped"] = True
                return result

            # Need transcript content to extract from
            if not transcript and not enhanced_notes:
                result["skipped"] = True
                return result

            # Build user prompt
            user_prompt = self._build_user_prompt(title, transcript, enhanced_notes, client_id)

            # Call LLM
            response = self._call_llm(user_prompt)
            if response is None:
                result["error"] = "Empty LLM response"
                return result

            # Parse JSON from response
            data = self._parse_json(response)
            if data is None:
                result["error"] = f"Failed to parse JSON from LLM response"
                return result

            # Process new todos
            new_todos = data.get("new_todos", [])
            if new_todos and client_id:
                items = []
                for todo in new_todos:
                    if not todo.get("title"):
                        continue
                    items.append({
                        "title": todo["title"],
                        "description": todo.get("description"),
                        "priority": todo.get("priority", 3),
                        "category": todo.get("category"),
                        "assigned_to": todo.get("assigned_to"),
                    })
                if items:
                    created = self.db.batch_create_todos(
                        client_id=client_id,
                        items=items,
                        meeting_id=meeting_id,
                        source_context=f"auto-extracted from '{title[:60]}'",
                    )
                    result["new_count"] = len(created)

            # Process completed todos
            completed_todos = data.get("completed_todos", [])
            if completed_todos and client_id:
                result["completed_count"] = self._process_completions(
                    client_id, completed_todos
                )

            # Mark extraction done
            self.db.mark_todos_extracted(meeting_id)

        except Exception as e:
            logger.error(f"Todo extraction failed for meeting {meeting_id}: {e}")
            result["error"] = str(e)

        return result

    def _build_user_prompt(self, title, transcript, enhanced_notes, client_id):
        parts = [f"Meeting: {title}"]

        if transcript:
            parts.append(f"\n## Transcript\n{transcript}")
        elif enhanced_notes:
            parts.append(f"\n## Notes\n{enhanced_notes}")

        # Include existing open todos for completion detection
        if client_id:
            try:
                existing = self.db.list_todos(client_id=client_id, include_done=False, limit=50)
                if existing:
                    lines = [f"\n## Open To-Dos (check if any were completed)"]
                    for t in existing:
                        lines.append(f"- [{t['id']}] {t['title']}")
                    parts.append("\n".join(lines))
            except Exception as e:
                logger.warning(f"Could not fetch existing todos: {e}")

        return "\n".join(parts)

    def _call_llm(self, user_prompt):
        try:
            client = self._get_client()
            response = client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            if response.content:
                return response.content[0].text
            return None
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return None

    def _parse_json(self, text):
        """Parse JSON from LLM response, handling markdown code fences."""
        # Strip markdown code fences if present
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', text.strip())
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error(f"JSON parse error. Response text: {text[:200]}")
            return None

    def _process_completions(self, client_id, completed_todos):
        """Match and complete todos based on LLM suggestions."""
        count = 0
        try:
            existing = self.db.list_todos(client_id=client_id, include_done=False, limit=100)
        except Exception:
            return 0

        for item in completed_todos:
            search = item.get("search", "")
            if not search:
                continue
            matches = TodoService.match_todos(existing, search)
            # Only complete if exactly one match (skip ambiguous)
            if len(matches) == 1:
                try:
                    self.db.complete_todo(matches[0]["id"])
                    count += 1
                    # Remove from list so subsequent matches don't re-match
                    existing = [t for t in existing if t["id"] != matches[0]["id"]]
                except Exception as e:
                    logger.warning(f"Could not complete todo {matches[0]['id']}: {e}")
        return count
