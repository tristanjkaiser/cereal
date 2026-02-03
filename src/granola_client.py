"""
Granola API client for fetching meeting notes.
Uses reverse-engineered API endpoint.
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional
import requests


class GranolaClient:
    """Client for accessing Granola meeting notes via their API."""

    API_BASE_URL = "https://api.granola.ai/v2"
    USER_AGENT = "Granola/5.354.0"
    CLIENT_VERSION = "5.354.0"

    def __init__(self, credentials_path: Optional[str] = None):
        """
        Initialize Granola client.

        Args:
            credentials_path: Path to supabase.json credentials file.
                            Defaults to ~/Library/Application Support/Granola/supabase.json
        """
        if credentials_path is None:
            credentials_path = os.path.expanduser(
                "~/Library/Application Support/Granola/supabase.json"
            )

        self.credentials_path = Path(credentials_path)
        self.access_token = self._load_access_token()

    def _load_access_token(self) -> str:
        """Load access token from Granola credentials file."""
        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"Granola credentials not found at {self.credentials_path}. "
                "Make sure Granola is installed and you're logged in."
            )

        with open(self.credentials_path, 'r') as f:
            creds = json.load(f)

        # The access token is nested inside the workos_tokens field (which is a JSON string)
        workos_tokens_str = creds.get('workos_tokens')
        if not workos_tokens_str:
            # Fallback: try to get access_token at top level (older format)
            access_token = creds.get('access_token')
            if access_token:
                return access_token
            raise ValueError(
                "No workos_tokens or access_token found in Granola credentials. "
                "Make sure you're logged in to Granola."
            )

        # Parse the workos_tokens JSON string
        try:
            workos_tokens = json.loads(workos_tokens_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse workos_tokens: {e}")

        # Extract access token from the parsed object
        access_token = workos_tokens.get('access_token')
        if not access_token:
            raise ValueError("No access_token found in workos_tokens")

        return access_token

    def _make_request(self, endpoint: str, data: Dict, debug: bool = False) -> Dict:
        """Make authenticated request to Granola API."""
        url = f"{self.API_BASE_URL}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "User-Agent": self.USER_AGENT,
            "X-Client-Version": self.CLIENT_VERSION,
        }

        if debug:
            print(f"\n🔍 DEBUG: Making request to {url}")
            print(f"   Payload: {data}")

        response = requests.post(url, json=data, headers=headers)

        if debug:
            print(f"   Status: {response.status_code}")
            print(f"   Response preview: {str(response.text)[:500]}...")

        response.raise_for_status()
        return response.json()

    def get_documents(self, limit: int = 10, offset: int = 0, debug: bool = False) -> List[Dict]:
        """
        Fetch meeting documents from Granola.

        Args:
            limit: Number of documents to fetch
            offset: Offset for pagination
            debug: Enable debug output

        Returns:
            List of document dictionaries
        """
        data = {
            "limit": limit,
            "offset": offset
        }

        result = self._make_request("get-documents", data, debug=debug)

        # API returns 'docs' not 'documents'
        docs = result.get('docs', result.get('documents', []))

        if debug:
            print(f"   Result keys: {result.keys()}")
            print(f"   Documents found: {len(docs)}")

        return docs

    def get_latest_document(self) -> Optional[Dict]:
        """Get the most recent meeting document."""
        docs = self.get_documents(limit=1)
        return docs[0] if docs else None

    def get_document_transcript(self, document_id: str, debug: bool = False) -> Optional[str]:
        """
        Fetch the raw transcript for a document.

        Args:
            document_id: Granola document ID
            debug: Enable debug output

        Returns:
            Formatted transcript string with speaker labels, or None if no transcript
        """
        data = {"document_id": document_id}

        if debug:
            print(f"\n🔍 Fetching transcript for document: {document_id}")

        try:
            # Use the v1 endpoint for transcripts
            url = "https://api.granola.ai/v1/get-document-transcript"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
                "User-Agent": self.USER_AGENT,
                "X-Client-Version": self.CLIENT_VERSION,
            }

            response = requests.post(url, json=data, headers=headers)

            if debug:
                print(f"   Transcript API Status: {response.status_code}")

            response.raise_for_status()

            transcript_segments = response.json()

            if not transcript_segments or len(transcript_segments) == 0:
                if debug:
                    print("   No transcript segments found")
                return None

            # Format transcript with speaker labels
            formatted_lines = []
            for segment in transcript_segments:
                source = segment.get('source', '')
                text = segment.get('text', '').strip()

                if not text:
                    continue

                if source == 'microphone':
                    formatted_lines.append(f"**Me:** {text}")
                elif source == 'system':
                    formatted_lines.append(f"**System:** {text}")
                else:
                    # Unknown source, just include the text
                    formatted_lines.append(text)

            formatted_transcript = "\n\n".join(formatted_lines)

            if debug:
                print(f"   Transcript length: {len(formatted_transcript)} characters")
                print(f"   Segments: {len(transcript_segments)}")

            return formatted_transcript

        except requests.exceptions.HTTPError as e:
            if debug:
                print(f"   HTTP Error fetching transcript: {e}")
            # Don't raise - transcript might not exist for all documents
            return None
        except Exception as e:
            if debug:
                print(f"   Error fetching transcript: {e}")
            return None

    def prosemirror_to_markdown(self, prosemirror_json: Dict, debug: bool = False) -> str:
        """
        Convert ProseMirror JSON to Markdown.

        Args:
            prosemirror_json: ProseMirror document JSON
            debug: Enable debug output

        Returns:
            Markdown string
        """
        def process_node(node: Dict, depth: int = 0, list_context: Optional[str] = None) -> str:
            """
            Recursively process ProseMirror nodes.

            Args:
                node: ProseMirror node
                depth: Current recursion depth
                list_context: 'bullet' or 'ordered' if inside a list
            """
            node_type = node.get('type', '')
            content = node.get('content', [])
            text = node.get('text', '')

            if debug and depth < 3:  # Limit debug output depth
                indent = "  " * depth
                print(f"{indent}Node: {node_type}, has_text: {bool(text)}, children: {len(content)}")

            # Process text nodes
            if text:
                marks = node.get('marks', [])
                result_text = text
                for mark in marks:
                    mark_type = mark.get('type', '')
                    if mark_type == 'bold':
                        result_text = f"**{result_text}**"
                    elif mark_type == 'italic':
                        result_text = f"*{result_text}*"
                    elif mark_type == 'code':
                        result_text = f"`{result_text}`"
                    elif mark_type == 'link':
                        href = mark.get('attrs', {}).get('href', '')
                        result_text = f"[{result_text}]({href})"
                return result_text

            # Process block nodes with children
            result = []
            for child in content:
                result.append(process_node(child, depth + 1, list_context))

            text_content = ''.join(result)

            # Handle different node types
            if node_type == 'doc':
                # Root document node
                return text_content

            elif node_type == 'paragraph':
                # Skip empty paragraphs
                if not text_content.strip():
                    return ''
                # Don't add extra newlines inside list items
                if list_context:
                    return text_content
                return text_content + '\n\n'

            elif node_type == 'heading':
                level = node.get('attrs', {}).get('level', 1)
                if not text_content.strip():
                    return ''
                return f"{'#' * level} {text_content}\n\n"

            elif node_type == 'bulletList':
                # Process as bullet list
                return text_content

            elif node_type == 'orderedList':
                # Process as numbered list
                return text_content

            elif node_type == 'listItem':
                # Determine if we're in ordered or bullet list
                if list_context == 'ordered':
                    # For ordered lists, we'd need to track position
                    # For now, use 1. for all items
                    return f"1. {text_content.strip()}\n"
                else:
                    # Bullet list item
                    return f"- {text_content.strip()}\n"

            elif node_type == 'codeBlock':
                language = node.get('attrs', {}).get('language', '')
                return f"```{language}\n{text_content}\n```\n\n"

            elif node_type == 'blockquote':
                # Add > prefix to each line
                lines = text_content.strip().split('\n')
                quoted = '\n'.join(f"> {line}" for line in lines)
                return f"{quoted}\n\n"

            elif node_type == 'hardBreak':
                return '\n'

            elif node_type == 'horizontalRule':
                return '---\n\n'

            else:
                # Unknown node type - just return content
                if debug:
                    print(f"  Unknown node type: {node_type}")
                return text_content

        if isinstance(prosemirror_json, dict):
            result = process_node(prosemirror_json)
            # Clean up multiple consecutive newlines
            while '\n\n\n' in result:
                result = result.replace('\n\n\n', '\n\n')
            return result.strip()
        return str(prosemirror_json)

    def get_document_as_markdown(self, document: Dict, debug: bool = False) -> str:
        """
        Extract and convert document content to Markdown.

        Combines Transcript, Enhanced Notes, and Manual Notes for comprehensive context.

        Args:
            document: Document dictionary from API
            debug: Enable debug output for ProseMirror parsing

        Returns:
            Markdown string combining all available note sources
        """
        if debug:
            print(f"\n🔍 Document fields: {list(document.keys())}")

        sections = []
        doc_id = document.get('id') or document.get('document_id')

        # 1. Transcript (raw meeting transcript with speaker labels)
        # Note: Always try to fetch transcript - the 'transcribe' flag is unreliable
        if doc_id:
            transcript = self.get_document_transcript(doc_id, debug=debug)
            if transcript:
                if debug:
                    print(f"   Transcript length: {len(transcript)}")
                sections.append("# Transcript\n\n" + transcript)

        # 2. Enhanced Notes (Granola's AI-generated notes)
        enhanced_notes = document.get('notes_markdown', '').strip()
        if enhanced_notes:
            if debug:
                print(f"   Enhanced notes length: {len(enhanced_notes)}")
            sections.append("# Enhanced Notes (by Granola)\n\n" + enhanced_notes)

        # 3. Manual Notes (user-typed notes in ProseMirror format)
        manual_content = (
            document.get('notes') or
            document.get('content') or
            document.get('prosemirror_content')
        )

        if manual_content:
            if debug:
                print(f"   Manual content type: {type(manual_content).__name__}")

            manual_markdown = ""
            if isinstance(manual_content, dict):
                manual_markdown = self.prosemirror_to_markdown(manual_content, debug=debug)
            elif isinstance(manual_content, str):
                try:
                    content_dict = json.loads(manual_content)
                    manual_markdown = self.prosemirror_to_markdown(content_dict, debug=debug)
                except json.JSONDecodeError:
                    manual_markdown = manual_content

            manual_markdown = manual_markdown.strip()

            # Only include manual notes if they have substantial content
            # and are different from enhanced notes
            if manual_markdown and len(manual_markdown) > 10:
                # Check if manual notes are essentially the same as enhanced notes
                if not enhanced_notes or manual_markdown != enhanced_notes.strip():
                    if debug:
                        print(f"   Manual notes length: {len(manual_markdown)}")
                    sections.append("# Manual Notes\n\n" + manual_markdown)
                elif debug:
                    print(f"   Manual notes skipped (duplicate of enhanced notes)")

        # Combine all sections
        if sections:
            combined = "\n\n---\n\n".join(sections)
            if debug:
                print(f"   Combined total length: {len(combined)}")
            return combined

        # Fallback: return any text field we can find
        fallback = document.get('notes_plain', '') or document.get('text', '')
        if debug and fallback:
            print(f"   Using fallback, length: {len(fallback)}")
        return fallback

    def get_document_content_parts(self, document: Dict, debug: bool = False) -> Dict[str, Optional[str]]:
        """
        Extract document content as separate components for database archival.

        Args:
            document: Document dictionary from API
            debug: Enable debug output

        Returns:
            Dictionary with keys: transcript, enhanced_notes, manual_notes, combined_markdown
        """
        doc_id = document.get('id') or document.get('document_id')

        # 1. Transcript
        transcript = None
        if doc_id:
            transcript = self.get_document_transcript(doc_id, debug=debug)

        # 2. Enhanced Notes (Granola's AI-generated notes)
        enhanced_notes = document.get('notes_markdown', '').strip() or None

        # 3. Manual Notes (user-typed notes in ProseMirror format)
        manual_notes = None
        manual_content = (
            document.get('notes') or
            document.get('content') or
            document.get('prosemirror_content')
        )

        if manual_content:
            if isinstance(manual_content, dict):
                manual_notes = self.prosemirror_to_markdown(manual_content, debug=debug)
            elif isinstance(manual_content, str):
                try:
                    content_dict = json.loads(manual_content)
                    manual_notes = self.prosemirror_to_markdown(content_dict, debug=debug)
                except json.JSONDecodeError:
                    manual_notes = manual_content

            if manual_notes:
                manual_notes = manual_notes.strip() or None

        # 4. Combined markdown (what gets sent to AI)
        combined_markdown = self.get_document_as_markdown(document, debug=debug)

        return {
            'transcript': transcript,
            'enhanced_notes': enhanced_notes,
            'manual_notes': manual_notes,
            'combined_markdown': combined_markdown
        }

    def get_document_attendees(self, document: Dict) -> List[Dict]:
        """
        Extract attendee list with email and company info from a document.

        Args:
            document: Document dictionary from API

        Returns:
            List of attendee dicts with 'email' and 'company' keys
        """
        attendees = []
        people = document.get('people', {})

        if not people:
            return attendees

        raw_attendees = people.get('attendees', [])

        for att in raw_attendees:
            email = att.get('email', '')
            details = att.get('details', {})
            company_info = details.get('company', {})
            company_name = company_info.get('name') if company_info else None

            attendees.append({
                'email': email,
                'company': company_name
            })

        return attendees
