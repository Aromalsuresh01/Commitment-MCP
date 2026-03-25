import unittest
import json
from unittest.mock import MagicMock
from datetime import datetime
from src.extraction import CommitmentExtractor
from src.models import Direction, CommitmentType

class TestExtraction(unittest.TestCase):
    def setUp(self):
        self.extractor = CommitmentExtractor(api_key="fake-key")
        self.extractor.client = MagicMock()

    def test_extract_commitments(self):
        # Mock Claude response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps([
            {
                "text": "I will send the report by Friday",
                "normalized": "Deliver the report",
                "direction": "outbound",
                "confidence": 0.95,
                "deadline_raw": "by Friday",
                "deadline_type": "explicit",
                "commitment_type": "deliver",
                "counterparty": "boss@example.com"
            }
        ]))]
        self.extractor.client.messages.create.return_value = mock_response

        commitments = self.extractor.extract_commitments(
            email_text="I will send the report by Friday",
            sender_is_me=True,
            email_date=datetime(2026, 3, 26),
            thread_id="thread1",
            message_id="msg1",
            counterparty="boss@example.com"
        )

        self.assertEqual(len(commitments), 1)
        c = commitments[0]
        self.assertEqual(c.normalized, "Deliver the report")
        self.assertEqual(c.direction, Direction.OUTBOUND)
        self.assertEqual(c.commitment_type, CommitmentType.DELIVER)
        self.assertGreater(c.urgency_score, 0)

    def test_urgency_score(self):
        # Create a mock commitment
        c = MagicMock()
        c.deadline_normalized = datetime(2026, 3, 25) # Yesterday (overdue)
        c.email_date = datetime(2026, 3, 20)
        c.direction = Direction.OUTBOUND
        c.extraction_confidence = 0.95
        
        score = self.extractor.compute_urgency_score(c)
        self.assertGreaterEqual(score, 50) # At least 50 for overdue

if __name__ == "__main__":
    import json
    unittest.main()
