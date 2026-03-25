import json
import uuid
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from anthropic import Anthropic
from src.models import Commitment, CommitmentType, CommitmentStatus, Direction, DeadlineType

logger = logging.getLogger("email-commitment-extractor.extraction")

class CommitmentExtractor:
    def __init__(self, api_key: str):
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-3-5-sonnet-20241022"

    def extract_commitments(self, email_text: str, sender_is_me: bool, 
                             email_date: datetime, thread_id: str, 
                             message_id: str, counterparty: str) -> List[Commitment]:
        """Calls Claude to extract commitments from a single email."""
        system_prompt = """
        You are a commitment extraction engine. Your job is to read email text and 
        identify explicit and implicit commitments. A commitment is any statement where:
        - A person agrees to take a specific action
        - A person sets a deadline or timeframe
        - A person promises to deliver something

        Return ONLY a JSON array. No preamble, no markdown.

        For each commitment, extract:
        {
          "text": "verbatim phrase from email",
          "normalized": "clear description in plain english",
          "direction": "outbound" | "inbound",
          "confidence": 0.0 - 1.0,
          "deadline_raw": "by Friday" | null,
          "deadline_type": "explicit" | "implicit" | "none",
          "commitment_type": "deliver" | "respond" | "schedule" | "review" | "other",
          "counterparty": "email address or name of the other party",
          "tags": ["tag1", "tag2"]
        }

        Rules:
        - "outbound" = [ME] is making the commitment
        - "inbound" = [THEM] is making the commitment to me
        - confidence < 0.6 = do not include
        - Vague pleasantries ("let's catch up sometime") = do not include
        - Calendar invites accepted = "schedule" commitment
        - Tags should categorize the work (e.g., "engineering", "legal", "personal", "finance")
        """
        
        role_marker = "[ME]" if sender_is_me else "[THEM]"
        prompt = f"Email Date: {email_date.isoformat()}\nSender: {role_marker}\nText: {email_text}"

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}]
        )

        try:
            raw_commitments = json.loads(response.content[0].text)
            commitments = []
            for item in raw_commitments:
                if item['confidence'] < 0.6:
                    continue
                
                # Normalize direction
                direction = Direction.OUTBOUND if item['direction'] == 'outbound' else Direction.INBOUND
                
                # Create Commitment object
                commitment = Commitment(
                    id=str(uuid.uuid4()),
                    thread_id=thread_id,
                    message_id=message_id,
                    extracted_at=datetime.now(),
                    email_date=email_date,
                    text=item['text'],
                    normalized=item['normalized'],
                    direction=direction,
                    commitment_type=CommitmentType(item['commitment_type']),
                    counterparty_email=counterparty,
                    deadline_raw=item['deadline_raw'],
                    deadline_type=DeadlineType(item['deadline_type']),
                    extraction_confidence=item['confidence'],
                    tags=item.get('tags', [])
                )
                
                # Normalize deadline
                commitment.deadline_normalized = self._normalize_deadline(item['deadline_raw'], email_date)
                
                # Compute urgency score
                commitment.urgency_score = self.compute_urgency_score(commitment)
                
                commitments.append(commitment)
            return commitments
        except (json.JSONDecodeError, KeyError, Exception) as e:
            logger.error(f"Error parsing Claude extraction response: {e}")
            return []

    def check_resolution(self, commitment: Commitment, subsequent_emails: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calls Claude to check if a commitment has been resolved."""
        if not subsequent_emails:
            return {"resolved": False, "confidence": 0.0}

        system_prompt = """
        You are checking whether a commitment was fulfilled in a later email.

        Was this commitment fulfilled? Respond ONLY with JSON:
        {
          "resolved": true | false,
          "confidence": 0.0 - 1.0,
          "evidence": "brief quote or description of what resolved it",
          "resolved_in_message_id": "gmail message id or null"
        }
        """

        thread_text = ""
        for msg in subsequent_emails:
            role = "[ME]" if msg.get('is_me') else "[THEM]"
            attach_info = " (HAS ATTACHMENTS)" if msg.get('has_attachments') else ""
            thread_text += f"Date: {msg['date']}\nSender: {role}{attach_info}\nText: {msg['text']}\n---\n"

        prompt = f"""
        Commitment: "{commitment.normalized}"
        Made by: {commitment.direction.value} on {commitment.email_date.isoformat()}

        Subsequent emails in this thread:
        {thread_text}
        """

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}]
        )

        try:
            return json.loads(response.content[0].text)
        except (json.JSONDecodeError, KeyError, Exception) as e:
            logger.error(f"Error parsing resolution response: {e}")
            return {"resolved": False, "confidence": 0.0}

    def _normalize_deadline(self, deadline_raw: Optional[str], email_date: datetime) -> Optional[datetime]:
        """Normalize deadlines using dateparser with email_date as the relative base."""
        if not deadline_raw:
            return None
        
        import dateparser
        
        raw = deadline_raw.lower()
        if "eod" in raw:
            return email_date.replace(hour=17, minute=0, second=0)
            
        parsed = dateparser.parse(
            raw,
            settings={
                'RELATIVE_BASE': email_date,
                'PREFER_DATES_FROM': 'future',
                'TIMEZONE': 'UTC',
                'RETURN_AS_TIMEZONE_AWARE': False
            }
        )
        
        if parsed:
            # If no time was specified, default to EOD (17:00)
            if parsed.hour == 0 and parsed.minute == 0:
                return parsed.replace(hour=17, minute=0, second=0)
            return parsed
            
        # Fallback to +3 days if dateparser fails
        return email_date + timedelta(days=3)

    def compute_urgency_score(self, commitment: Commitment) -> float:
        """Computes urgency score (0-100) based on the PRD formula."""
        score = 0.0
        now = datetime.now()
        
        # Deadline score
        if commitment.deadline_normalized:
            diff = (commitment.deadline_normalized - now).days
            if diff < 0: score += 50 # Overdue
            elif diff == 0: score += 40 # Due today
            elif diff <= 2: score += 30 # Due within 2 days
            elif diff <= 7: score += 20 # Due within 7 days
            elif diff <= 30: score += 10 # Due within 30 days
        else:
            score += 5 # No deadline
            
        # Staleness score (days since email with no resolution)
        days_since = (now - commitment.email_date).days
        if days_since >= 30: score += 20
        elif days_since >= 15: score += 15
        elif days_since >= 8: score += 10
        elif days_since >= 4: score += 5
        
        # Direction weight
        if commitment.direction == Direction.OUTBOUND:
            score += 10
        else:
            score += 5
            
        # Confidence weight
        if commitment.extraction_confidence > 0.9:
            score += 5
        elif commitment.extraction_confidence > 0.7:
            score += 2
            
        return min(100.0, score)
