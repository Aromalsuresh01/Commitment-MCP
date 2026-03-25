import os
import asyncio
import email.utils
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server.stdio import stdio_server
from dotenv import load_dotenv

from src.db import Database
from src.gmail_client import GmailClient
from src.extraction import CommitmentExtractor
from src.models import Commitment, CommitmentStatus, Direction, SyncState

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("server.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("email-commitment-server")

class EmailCommitmentServer:
    def __init__(self):
        self.server = Server("email-commitment-extractor")
        self.db = Database()
        try:
            self.gmail = GmailClient()
        except Exception as e:
            print(f"Warning: Gmail client initialization failed: {e}")
            self.gmail = None
        
        self.extractor = CommitmentExtractor(os.getenv("ANTHROPIC_API_KEY"))
        self._setup_tools()

    def _setup_tools(self):
        @self.server.list_tools()
        async def list_tools() -> List[types.Tool]:
            return [
                types.Tool(
                    name="sync_emails",
                    description="Pull new emails from Gmail and run extraction",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "max_emails": {"type": "integer", "default": 10}
                        }
                    }
                ),
                types.Tool(
                    name="get_commitments",
                    description="Return filtered/sorted commitment list",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "status": {"type": "string", "enum": ["open", "resolved", "overdue", "uncertain", "dismissed"]},
                            "direction": {"type": "string", "enum": ["outbound", "inbound"]},
                            "limit": {"type": "integer", "default": 20}
                        }
                    }
                ),
                types.Tool(
                    name="get_commitment_detail",
                    description="Full detail on a single commitment with thread context",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"}
                        },
                        "required": ["id"]
                    }
                ),
                types.Tool(
                    name="mark_resolved",
                    description="Manually mark a commitment as done",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"}
                        },
                        "required": ["id"]
                    }
                ),
                types.Tool(
                    name="get_summary",
                    description="High-level stats: how many open, overdue, by person",
                    inputSchema={"type": "object", "properties": {}}
                ),
                types.Tool(
                    name="search_commitments",
                    description="Full-text search over commitment descriptions",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer", "default": 20}
                        },
                        "required": ["query"]
                    }
                ),
                types.Tool(
                    name="run_eval",
                    description="Run accuracy evaluation over a dataset and return metrics",
                    inputSchema={"type": "object", "properties": {}}
                )
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> List[types.TextContent]:
            try:
                if name == "sync_emails":
                    return await self.sync_emails(arguments.get("max_emails", 10))
                elif name == "get_commitments":
                    return await self.get_commitments_tool(
                        arguments.get("status"), 
                        arguments.get("direction"),
                        arguments.get("limit", 20)
                    )
                elif name == "get_commitment_detail":
                    return await self.get_commitment_detail_tool(arguments["id"])
                elif name == "mark_resolved":
                    return await self.mark_resolved_tool(arguments["id"])
                elif name == "get_summary":
                    return await self.get_summary_tool()
                elif name == "search_commitments":
                    return await self.search_commitments_tool(
                        arguments["query"],
                        arguments.get("limit", 20)
                    )
                elif name == "run_eval":
                    return await self.run_eval_tool()
                else:
                    raise ValueError(f"Unknown tool: {name}")
            except Exception as e:
                logger.exception(f"Error executing tool {name}")
                import json
                return [types.TextContent(type="text", text=json.dumps({"error": str(e), "success": False}))]

    def _parse_email(self, raw_val: str) -> str:
        """Helper to extract email address from raw header string."""
        name, addr = email.utils.parseaddr(raw_val)
        return addr.lower()

    async def sync_emails(self, max_emails: int) -> List[types.TextContent]:
        if not self.gmail:
            return [types.TextContent(type="text", text="Error: Gmail client not initialized. Check credentials.json.")]
            
        state = self.db.get_sync_state(self.gmail.user_email)
        if not state:
            state = SyncState(
                account_email=self.gmail.user_email,
                last_sync_at=datetime.now()
            )
        
        # In a real app, we'd use state.last_history_id for incremental sync
        # For simplicity in this version, we'll just fetch the most recent messages
        messages = self.gmail.get_messages(max_results=max_emails)
        
        commitments_found = 0
        emails_skipped = 0
        
        for msg_info in messages:
            try:
                msg_id = msg_info['id']
                msg_detail = self.gmail.get_message_detail(msg_id)
                if not msg_detail:
                    logger.warning(f"Could not fetch details for message {msg_id}")
                    continue
                    
                headers = self.gmail.parse_message_headers(msg_detail)
                body = self.gmail.extract_body_text(msg_detail.get('payload', {}))
                
                if not body:
                    emails_skipped += 1
                    continue
                
                sender_email = self._parse_email(headers.get('from', ''))
                
                # Cache the email content
                try:
                    self.db.upsert_email_cache(
                        message_id=msg_id,
                        thread_id=msg_detail['threadId'],
                        raw_content=body,
                        sender_email=sender_email,
                        subject=headers.get('subject', ''),
                        date=headers.get('date', datetime.now().isoformat())
                    )
                except Exception as cache_err:
                    logger.warning(f"Failed to cache email {msg_id}: {cache_err}")

                sender_is_me = sender_email == self.gmail.user_email.lower()
                counterparty = headers.get('to') if sender_is_me else headers.get('from')
                email_date = datetime.now() # Fallback
                if 'date' in headers:
                    try:
                        parsed_date = email.utils.parsedate_to_datetime(headers['date'])
                        email_date = parsed_date.replace(tzinfo=None) # Keep naive
                    except Exception as date_err:
                        logger.warning(f"Failed to parse date '{headers.get('date')}' for message {msg_id}: {date_err}")

                extracted = self.extractor.extract_commitments(
                    email_text=body,
                    sender_is_me=sender_is_me,
                    email_date=email_date,
                    thread_id=msg_detail['threadId'],
                    message_id=msg_id,
                    counterparty=counterparty
                )
                
                if extracted:
                    # Fetch thread once per email
                    try:
                        thread = self.gmail.get_thread(msg_detail['threadId'])
                        subsequent_emails = []
                        if thread and 'messages' in thread:
                            for t_msg in thread['messages']:
                                try:
                                    if int(t_msg['internalDate']) > int(msg_detail['internalDate']):
                                        t_body = self.gmail.extract_body_text(t_msg.get('payload', {}))
                                        t_headers = self.gmail.parse_message_headers(t_msg)
                                        t_is_me = t_headers.get('from', '').lower() == self.gmail.user_email.lower()
                                        has_attachments = self.gmail.has_attachments(t_msg.get('payload', {}))
                                        subsequent_emails.append({
                                            'text': t_body,
                                            'date': t_headers.get('date'),
                                            'is_me': t_is_me,
                                            'has_attachments': has_attachments,
                                            'message_id': t_msg['id']
                                        })
                                except Exception as t_msg_err:
                                    logger.error(f"Error processing thread message {t_msg.get('id')} in thread {msg_detail['threadId']}: {t_msg_err}")

                            for c in extracted:
                                try:
                                    # Check for duplicates first
                                    existing = self.db.find_duplicate(c.thread_id, c.normalized, c.direction)
                                    if existing:
                                        # Update existing if new one has better data
                                        if c.deadline_normalized and not existing.deadline_normalized:
                                            existing.deadline_normalized = c.deadline_normalized
                                            existing.deadline_raw = c.deadline_raw
                                            self.db.upsert_commitment(existing)
                                        continue

                                    # Check resolution in thread
                                    res = self.extractor.check_resolution(c, subsequent_emails)
                                    if res.get('resolved'):
                                        c.status = CommitmentStatus.RESOLVED
                                        c.resolved_at = datetime.now()
                                        c.resolved_message_id = res.get('resolved_in_message_id')
                                        c.resolution_confidence = res.get('confidence')
                                    
                                    self.db.upsert_commitment(c)
                                    commitments_found += 1
                                except Exception as c_err:
                                    logger.error(f"Error processing commitment '{c.normalized}' for message {msg_id}: {c_err}")
                    except Exception as thread_err:
                        logger.error(f"Error fetching/processing thread {msg_detail['threadId']}: {thread_err}")
            except Exception as msg_err:
                logger.error(f"Error processing message {msg_info.get('id')}: {msg_err}")
        
        try:
            state.last_sync_at = datetime.now()
            state.total_commitments_extracted += commitments_found
            state.total_emails_processed += len(messages)
            self.db.update_sync_state(state)
        except Exception as db_err:
            logger.error(f"Failed to update sync state in database: {db_err}")
        
        return [types.TextContent(type="text", text=f"Synced {len(messages)} emails (skipped {emails_skipped} empty), found {commitments_found} new commitments.")]

    async def get_commitments_tool(self, status: str, direction: str, limit: int) -> List[types.TextContent]:
        try:
            status_enum = CommitmentStatus(status) if status else None
            dir_enum = Direction(direction) if direction else None
            commitments = self.db.get_commitments(status=status_enum, direction=dir_enum, limit=limit)
            
            if not commitments:
                return [types.TextContent(type="text", text="No commitments found.")]

            output = "### Commitments\n\n"
            for c in commitments:
                tags_str = f" [{', '.join(c.tags)}]" if c.tags else ""
                output += f"- **{c.normalized}**{tags_str} (Status: {c.status.value}, Priority: {c.urgency_score:.0f}, ID: {c.id})\n"
                output += f"  - From: {c.counterparty_email} | Deadline: {c.deadline_raw or 'None'}\n"
            
            return [types.TextContent(type="text", text=output)]
        except Exception as e:
            logger.error(f"Error in get_commitments_tool: {e}")
            raise

    async def get_commitment_detail_tool(self, commitment_id: str) -> List[types.TextContent]:
        try:
            if not commitment_id:
                return [types.TextContent(type="text", text="Error: commitment_id is required.")]
                
            c = self.db.get_commitment(commitment_id)
            if not c:
                return [types.TextContent(type="text", text=f"Commitment {commitment_id} not found.")]
            
            deadline_str = f"{c.deadline_raw or 'None'}"
            if c.deadline_normalized:
                deadline_str += f" ({c.deadline_normalized.strftime('%Y-%m-%d')})"
            
            output = f"### {c.normalized}\n"
            output += f"- **Original text:** \"{c.text}\"\n"
            output += f"- **Direction:** {c.direction.value}\n"
            output += f"- **Status:** {c.status.value}\n"
            output += f"- **Urgency Score:** {c.urgency_score:.0f}\n"
            output += f"- **Counterparty:** {c.counterparty_email}\n"
            output += f"- **Deadline:** {deadline_str}\n"
            if c.tags:
                output += f"- **Tags:** {', '.join(c.tags)}\n"
            
            return [types.TextContent(type="text", text=output)]
        except Exception as e:
            logger.error(f"Error in get_commitment_detail_tool for ID {commitment_id}: {e}")
            raise

    async def mark_resolved_tool(self, commitment_id: str) -> List[types.TextContent]:
        try:
            if not commitment_id:
                return [types.TextContent(type="text", text="Error: commitment_id is required.")]
                
            c = self.db.get_commitment(commitment_id)
            if not c:
                return [types.TextContent(type="text", text=f"Commitment {commitment_id} not found.")]
            
            c.status = CommitmentStatus.RESOLVED
            c.resolved_at = datetime.now()
            self.db.upsert_commitment(c)
            return [types.TextContent(type="text", text=f"Marked commitment '{c.normalized}' as resolved.")]
        except Exception as e:
            logger.error(f"Error in mark_resolved_tool for ID {commitment_id}: {e}")
            raise

    async def get_summary_tool(self) -> List[types.TextContent]:
        # Simple summary implementation
        commitments = self.db.get_commitments(limit=1000)
        open_count = sum(1 for c in commitments if c.status == CommitmentStatus.OPEN)
        resolved_count = sum(1 for c in commitments if c.status == CommitmentStatus.RESOLVED)
        overdue_count = sum(1 for c in commitments if c.status == CommitmentStatus.OVERDUE)
        
        output = "### Commitment Summary\n"
        output += f"- **Open:** {open_count}\n"
        output += f"- **Resolved:** {resolved_count}\n"
        output += f"- **Overdue:** {overdue_count}\n"
        
        return [types.TextContent(type="text", text=output)]

    async def search_commitments_tool(self, query: str, limit: int) -> List[types.TextContent]:
        commitments = self.db.search_commitments(query, limit)
        if not commitments:
            return [types.TextContent(type="text", text=f"No commitments found matching '{query}'.")]
        
        output = f"### Search Results for '{query}'\n\n"
        for c in commitments:
            output += f"- **{c.normalized}** (Status: {c.status.value}, Priority: {c.urgency_score:.0f}, ID: {c.id})\n"
            output += f"  - From: {c.counterparty_email} | Deadline: {c.deadline_raw or 'None'}\n"
        
        return [types.TextContent(type="text", text=output)]

    async def run_eval_tool(self) -> List[types.TextContent]:
        from src.eval import EvaluationRunner
        try:
            runner = EvaluationRunner(self.extractor)
            results = runner.run_evaluation()
            import json
            return [types.TextContent(type="text", text=json.dumps(results, indent=2))]
        except Exception as e:
            logger.error(f"Error running eval: {e}")
            raise

    async def run(self):
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="email-commitment-extractor",
                    server_version="1.0.0",
                    capabilities=self.server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )

if __name__ == "__main__":
    server = EmailCommitmentServer()
    asyncio.run(server.run())
