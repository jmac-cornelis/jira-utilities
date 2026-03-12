from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.utils import extract_text_from_adf
from notifications.base import NotificationBackend


class JiraCommentNotifier(NotificationBackend):
    MARKER = '[PM-Agent]'

    _LEVEL_STYLES = {
        'auto_fill': {'panel_type': 'success', 'icon': '✅', 'title': 'Auto-fill applied'},
        'suggest': {'panel_type': 'warning', 'icon': '💡', 'title': 'Suggestion'},
        'flag': {'panel_type': 'error', 'icon': '⚠️', 'title': 'Missing required fields'},
    }

    def __init__(self, jira: Any):
        self.jira = jira

    def _normalize_level(self, level: Optional[str]) -> str:
        if not level:
            return 'flag'

        normalized = str(level).strip().lower()
        if normalized in self._LEVEL_STYLES:
            return normalized

        return 'flag'

    def _build_adf_comment(self, message: str, level: str) -> Dict[str, Any]:
        style = self._LEVEL_STYLES[self._normalize_level(level)]
        text = f"{self.MARKER} {style['icon']} {style['title']}: {message}"

        return {
            'type': 'doc',
            'version': 1,
            'content': [
                {
                    'type': 'panel',
                    'attrs': {'panelType': style['panel_type']},
                    'content': [
                        {
                            'type': 'paragraph',
                            'content': [
                                {'type': 'text', 'text': text},
                            ],
                        }
                    ],
                }
            ],
        }

    def _comment_text(self, comment_body: Any) -> str:
        return extract_text_from_adf(comment_body)

    def has_existing_comment(self, ticket_key: str, field: Optional[str] = None) -> bool:
        try:
            comments = self.jira.comments(ticket_key)
        except Exception:
            return False

        field_token = str(field).strip().lower() if field else None

        for comment in comments:
            body = getattr(comment, 'body', '')
            text = self._comment_text(body)
            normalized = text.lower()

            if self.MARKER.lower() not in normalized:
                continue

            if field_token and field_token not in normalized:
                continue

            return True

        return False

    def send(
        self,
        ticket_key: str,
        message: str,
        level: str = 'flag',
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        ctx = context or {}
        field = ctx.get('field')

        if self.has_existing_comment(ticket_key, field=field):
            return False

        adf = self._build_adf_comment(message=message, level=level)

        try:
            self.jira.add_comment(ticket_key, adf)
            return True
        except Exception:
            return False

    def send_auto_fill(
        self,
        ticket_key: str,
        field: str,
        value: str,
        confidence: float,
        reason: str,
    ) -> bool:
        message = (
            f"Set {field} to {value} based on {reason}. "
            f"Confidence: {confidence:.0%}. Please correct if needed."
        )
        return self.send(ticket_key, message, level='auto_fill', context={'field': field})

    def send_suggestion(
        self,
        ticket_key: str,
        field: str,
        value: str,
        confidence: float,
        reason: str,
    ) -> bool:
        message = (
            f"This looks like {field}={value} based on {reason}. "
            f"Confidence: {confidence:.0%}. Can you confirm?"
        )
        return self.send(ticket_key, message, level='suggest', context={'field': field})

    def send_flag(self, ticket_key: str, missing_fields: List[str]) -> bool:
        joined = ', '.join(missing_fields)
        message = f'Missing required field(s): {joined}. Please update this ticket.'
        return self.send(
            ticket_key,
            message,
            level='flag',
            context={'field': joined.lower()},
        )
