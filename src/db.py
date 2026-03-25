import sqlite3
import json
from datetime import datetime
from typing import List, Optional
from src.models import Commitment, CommitmentStatus, Direction, CommitmentType, DeadlineType, SyncState

class Database:
    def __init__(self, db_path: str = "commitments.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Create commitments table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS commitments (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    extracted_at TEXT NOT NULL,
                    email_date TEXT NOT NULL,
                    text TEXT NOT NULL,
                    normalized TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    commitment_type TEXT NOT NULL,
                    counterparty_email TEXT NOT NULL,
                    counterparty_name TEXT,
                    deadline_raw TEXT,
                    deadline_normalized TEXT,
                    deadline_type TEXT NOT NULL DEFAULT 'none',
                    status TEXT NOT NULL DEFAULT 'open',
                    resolved_at TEXT,
                    resolved_message_id TEXT,
                    resolution_confidence REAL,
                    extraction_confidence REAL NOT NULL,
                    urgency_score REAL DEFAULT 0.0,
                    notes TEXT,
                    tags TEXT -- stored as JSON string
                )
            """)
            
            # Create sync_state table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_state (
                    account_email TEXT PRIMARY KEY,
                    last_sync_at TEXT NOT NULL,
                    last_history_id TEXT,
                    total_emails_processed INTEGER DEFAULT 0,
                    total_commitments_extracted INTEGER DEFAULT 0
                )
            """)
            
            # Create extraction_runs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS extraction_runs (
                    id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    emails_processed INTEGER DEFAULT 0,
                    commitments_found INTEGER DEFAULT 0,
                    tokens_used INTEGER DEFAULT 0,
                    errors TEXT -- stored as JSON string
                )
            """)
            
            conn.commit()

    def upsert_commitment(self, commitment: Commitment):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO commitments (
                    id, thread_id, message_id, extracted_at, email_date,
                    text, normalized, direction, commitment_type,
                    counterparty_email, counterparty_name,
                    deadline_raw, deadline_normalized, deadline_type,
                    status, resolved_at, resolved_message_id, resolution_confidence,
                    extraction_confidence, urgency_score, notes, tags
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                commitment.id, commitment.thread_id, commitment.message_id,
                commitment.extracted_at.isoformat(), commitment.email_date.isoformat(),
                commitment.text, commitment.normalized, commitment.direction.value,
                commitment.commitment_type.value, commitment.counterparty_email,
                commitment.counterparty_name, commitment.deadline_raw,
                commitment.deadline_normalized.isoformat() if commitment.deadline_normalized else None,
                commitment.deadline_type.value, commitment.status.value,
                commitment.resolved_at.isoformat() if commitment.resolved_at else None,
                commitment.resolved_message_id, commitment.resolution_confidence,
                commitment.extraction_confidence, commitment.urgency_score,
                commitment.notes, json.dumps(commitment.tags)
            ))
            conn.commit()

    def get_commitment(self, commitment_id: str) -> Optional[Commitment]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM commitments WHERE id = ?", (commitment_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_commitment(row)
            return None

    def get_commitments(self, status: Optional[CommitmentStatus] = None, 
                        direction: Optional[Direction] = None,
                        limit: int = 50, offset: int = 0) -> List[Commitment]:
        query = "SELECT * FROM commitments WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status.value)
        if direction:
            query += " AND direction = ?"
            params.append(direction.value)
        
        query += " ORDER BY urgency_score DESC, email_date DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            return [self._row_to_commitment(row) for row in cursor.fetchall()]

    def _row_to_commitment(self, row: sqlite3.Row) -> Commitment:
        return Commitment(
            id=row['id'],
            thread_id=row['thread_id'],
            message_id=row['message_id'],
            extracted_at=datetime.fromisoformat(row['extracted_at']),
            email_date=datetime.fromisoformat(row['email_date']),
            text=row['text'],
            normalized=row['normalized'],
            direction=Direction(row['direction']),
            commitment_type=CommitmentType(row['commitment_type']),
            counterparty_email=row['counterparty_email'],
            counterparty_name=row['counterparty_name'],
            deadline_raw=row['deadline_raw'],
            deadline_normalized=datetime.fromisoformat(row['deadline_normalized']) if row['deadline_normalized'] else None,
            deadline_type=DeadlineType(row['deadline_type']),
            status=CommitmentStatus(row['status']),
            resolved_at=datetime.fromisoformat(row['resolved_at']) if row['resolved_at'] else None,
            resolved_message_id=row['resolved_message_id'],
            resolution_confidence=row['resolution_confidence'],
            extraction_confidence=row['extraction_confidence'],
            urgency_score=row['urgency_score'],
            notes=row['notes'],
            tags=json.loads(row['tags']) if row['tags'] else []
        )

    def get_sync_state(self, account_email: str) -> Optional[SyncState]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sync_state WHERE account_email = ?", (account_email,))
            row = cursor.fetchone()
            if row:
                return SyncState(
                    account_email=row['account_email'],
                    last_sync_at=datetime.fromisoformat(row['last_sync_at']),
                    last_history_id=row['last_history_id'],
                    total_emails_processed=row['total_emails_processed'],
                    total_commitments_extracted=row['total_commitments_extracted']
                )
            return None

    def find_duplicate(self, thread_id: str, normalized_text: str, direction: Direction) -> Optional[Commitment]:
        """Finds an existing commitment in the same thread with similar text and direction."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # Simple exact match or very similar match for now
            # In production, we'd use cosine similarity on embeddings
            cursor.execute("""
                SELECT * FROM commitments 
                WHERE thread_id = ? AND direction = ? 
                AND (normalized = ? OR normalized LIKE ?)
            """, (thread_id, direction.value, normalized_text, f"%{normalized_text[:10]}%"))
            row = cursor.fetchone()
            if row:
                return self._row_to_commitment(row)
            return None

    def search_commitments(self, query: str, limit: int = 20) -> List[Commitment]:
        """Full-text search over normalized commitment descriptions."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM commitments 
                WHERE normalized LIKE ? OR text LIKE ?
                ORDER BY urgency_score DESC
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit))
            return [self._row_to_commitment(row) for row in cursor.fetchall()]

    def update_sync_state(self, state: SyncState):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO sync_state (
                    account_email, last_sync_at, last_history_id,
                    total_emails_processed, total_commitments_extracted
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                state.account_email, state.last_sync_at.isoformat(),
                state.last_history_id, state.total_emails_processed,
                state.total_commitments_extracted
            ))
            conn.commit()
