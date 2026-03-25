# Product Requirements Document
## Email Commitment Extractor — MCP Server
**Version:** 1.0.0  
**Status:** Draft  
**Author:** AI Engineer Portfolio Project  
**Last Updated:** March 2026

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Goals & Non-Goals](#3-goals--non-goals)
4. [User Personas](#4-user-personas)
5. [System Architecture](#5-system-architecture)
6. [MCP Server Specification](#6-mcp-server-specification)
7. [Commitment Extraction Engine](#7-commitment-extraction-engine)
8. [Data Models](#8-data-models)
9. [Gmail Integration](#9-gmail-integration)
10. [Resolution Detection](#10-resolution-detection)
11. [Scoring & Prioritization](#11-scoring--prioritization)
12. [Storage & State Management](#12-storage--state-management)
13. [Evaluation & Accuracy](#13-evaluation--accuracy)
14. [API Reference](#14-api-reference)
15. [Code Standards](#15-code-standards)
16. [Error Handling](#16-error-handling)
17. [Testing Strategy](#17-testing-strategy)
18. [Milestones](#18-milestones)
19. [Open Questions](#19-open-questions)
20. [Agent Implementation Guide](#20-agent-implementation-guide)

---

## 1. Executive Summary

**Email Commitment Extractor** is an MCP (Model Context Protocol) server that connects to a user's Gmail account, scans sent and received emails, and uses Claude to extract explicit and implicit commitments — things you promised to do, deadlines you set, and things others promised you. It surfaces these as a structured, ranked, real-time tracker so nothing falls through the cracks.

This is a portfolio-grade project that demonstrates:
- MCP server design and tooling
- Structured extraction with LLMs
- Multi-turn resolution tracking
- Evaluation pipelines for NLP tasks

---

## 2. Problem Statement

### The Core Pain

Email is where commitments go to die. Every professional makes dozens of micro-promises per week scattered across hundreds of threads:

- *"I'll send the deck by EOD Friday"*
- *"Let me loop in our legal team"*
- *"Can you share the report? I'll review it this week"*
- *"We'll have pricing ready before the call"*

None of these get tracked. There is no unified dashboard. The only recovery mechanism is anxious ctrl+F searches through sent mail — and even then, you don't know if the thing got done.

### Why Existing Tools Fail

| Tool | Limitation |
|------|-----------|
| Gmail reminders | Manual, per-email, no extraction |
| Task managers (Todoist, Asana) | Require manual entry from email |
| CRM follow-up tools | Sales-only, not general commitment tracking |
| Email clients (Superhuman, HEY) | Surface snoozing, not commitment extraction |
| LLM email summarizers | Summarize threads, don't track cross-thread commitments |

### The Gap

No tool does all three of:
1. **Automatically extract** commitments from natural language email text
2. **Track resolution** — did the commitment actually get fulfilled in a later message?
3. **Surface bidirectional obligations** — what you owe others AND what others owe you

---

## 3. Goals & Non-Goals

### Goals

- Extract commitments from Gmail sent and received mail automatically
- Classify commitments as **outbound** (you owe) or **inbound** (others owe you)
- Detect deadlines — explicit ("by Friday") and implicit ("soon", "this week")
- Detect resolution — did a subsequent email fulfill the commitment?
- Score and prioritize commitments by urgency and staleness
- Expose all of this as MCP tools that Claude can call conversationally
- Achieve >85% precision and >75% recall on commitment extraction (see §13)

### Non-Goals (v1.0)

- Calendar integration (v2)
- Slack / Teams commitment extraction (v2)
- Mobile push notifications (v2)
- Multi-account Gmail support (v2)
- Auto-reply drafting to follow up on inbound commitments (v2)
- Support for languages other than English (v2)

---

## 4. User Personas

### Primary: The Busy Knowledge Worker
- Sends 30–80 emails/day
- Manages multiple ongoing projects with different stakeholders
- Frequently misses follow-ups due to volume
- Wants a conversational way to ask "what have I promised this week?"

### Secondary: The AI Engineer (Portfolio Audience)
- Hiring managers and technical interviewers reviewing the project
- Wants to see: clean MCP tool design, LLM prompt engineering, eval methodology
- Will look at code quality, comments, error handling, and schema design

---

## 5. System Architecture

```
┌─────────────────────────────────────────────────┐
│                  Claude (Client)                 │
│         Calls MCP tools conversationally         │
└────────────────────┬────────────────────────────┘
                     │ MCP Protocol (SSE / stdio)
┌────────────────────▼────────────────────────────┐
│           Email Commitment MCP Server            │
│                                                  │
│  ┌─────────────┐   ┌──────────────────────────┐ │
│  │  Tool Layer │   │   Extraction Engine       │ │
│  │  (MCP tools)│   │   (Claude API calls)      │ │
│  └──────┬──────┘   └────────────┬─────────────┘ │
│         │                       │               │
│  ┌──────▼───────────────────────▼─────────────┐ │
│  │            State Manager                    │ │
│  │    (SQLite — commitments, threads, cache)   │ │
│  └──────────────────┬──────────────────────────┘│
└─────────────────────┼───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│              Gmail MCP Server                    │
│         (google gmail connector)                 │
└─────────────────────────────────────────────────┘
```

### Key Design Decisions

- **MCP over REST**: Exposing tools via MCP lets Claude reason over commitments conversationally without a separate frontend
- **SQLite for state**: Lightweight, portable, zero-ops. Stores extracted commitments and resolution status
- **Extraction via Claude API**: Use `claude-sonnet-4-20250514` for extraction — fast, cheap, accurate on structured tasks
- **Incremental sync**: Only process new emails since last sync — don't re-scan the entire inbox every time

---

## 6. MCP Server Specification

### Transport

The server supports two transport modes:

| Mode | Use Case | Config |
|------|----------|--------|
| `stdio` | Local dev, Claude Desktop, Claude Code | `--transport stdio` |
| `SSE (HTTP)` | Hosted, Claude.ai connector | `--transport sse --port 3000` |

### Server Metadata

```json
{
  "name": "email-commitment-extractor",
  "version": "1.0.0",
  "description": "Extracts and tracks commitments from Gmail threads",
  "author": "your-name"
}
```

### Exposed MCP Tools

| Tool Name | Description |
|-----------|-------------|
| `sync_emails` | Pull new emails from Gmail and run extraction |
| `get_commitments` | Return filtered/sorted commitment list |
| `get_commitment_detail` | Full detail on a single commitment with thread context |
| `mark_resolved` | Manually mark a commitment as done |
| `get_summary` | High-level stats: how many open, overdue, by person |
| `get_inbound` | Commitments others made to you |
| `search_commitments` | Full-text search over commitment descriptions |
| `get_overdue` | All commitments past their deadline |

---

## 7. Commitment Extraction Engine

This is the core intellectual challenge of the project. The extraction engine uses a multi-stage pipeline to maximize accuracy.

### Stage 1 — Email Preprocessing

Before sending to Claude, clean and structure the raw email:

```
- Strip quoted/forwarded text (only process new content per email)
- Strip email signatures (detected via heuristics: "-- ", "Best,", "Thanks,")
- Normalize whitespace, HTML entities
- Truncate threads longer than 4,000 tokens (keep most recent messages)
- Tag each message segment with sender role: [ME] or [THEM]
```

**Why strip quoted text?** Without this, the same commitment gets extracted multiple times from the same thread — once per reply that quotes the original message. This is the single biggest source of false duplicates.

### Stage 2 — Commitment Detection Prompt

Send the cleaned email to Claude with a carefully engineered prompt:

```
SYSTEM:
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
  "counterparty": "email address or name of the other party"
}

Rules:
- "outbound" = [ME] is making the commitment
- "inbound" = [THEM] is making the commitment to me
- confidence < 0.6 = do not include
- Vague pleasantries ("let's catch up sometime") = do not include
- Calendar invites accepted = "schedule" commitment
```

### Stage 3 — Deadline Normalization

Raw deadline strings ("by EOD Friday", "next week", "before the call") need to be converted to absolute dates. Use a secondary Claude call or a rule-based parser:

```
Heuristic resolution order:
1. Explicit dates: "March 15", "3/15" → parse directly
2. Day-of-week: "by Friday" → next upcoming Friday relative to email send date
3. Named periods: "EOD" → 5pm same day, "this week" → Sunday, "next week" → following Sunday
4. Implicit: "soon", "shortly" → +3 days (configurable)
5. None: no deadline stored, urgency scored lower
```

### Stage 4 — Deduplication

The same logical commitment often appears across multiple emails in a thread. Before storing, deduplicate:

```
Two commitments are duplicates if:
- Same thread_id AND
- Normalized text similarity > 0.85 (use cosine similarity on embeddings) AND
- Same direction (outbound/inbound)

Resolution: keep the one with the more explicit deadline; otherwise keep earliest
```

### Stage 5 — Resolution Detection

After extraction, run a second pass to check if the commitment was later resolved in the same thread:

```
A commitment is RESOLVED if a subsequent email in the same thread contains:
- Delivery signal: attachment sent, link shared, document referenced
- Acknowledgment signal: "thanks for sending", "got it", "received"
- Completion signal: "done", "sent", "shared", "here it is"

Resolution confidence threshold: 0.75
If below threshold, mark as UNCERTAIN (not resolved, not open)
```

---

## 8. Data Models

### Commitment

```typescript
// Core commitment record stored in SQLite
interface Commitment {
  id: string;                   // UUID
  thread_id: string;            // Gmail thread ID
  message_id: string;           // Gmail message ID of source email
  extracted_at: string;         // ISO 8601 timestamp of when extracted
  email_date: string;           // ISO 8601 timestamp of source email
  
  text: string;                 // Verbatim phrase from email
  normalized: string;           // Plain English description
  
  direction: "outbound" | "inbound";  // Who made the commitment
  commitment_type: CommitmentType;
  counterparty_email: string;
  counterparty_name: string | null;
  
  deadline_raw: string | null;       // Original deadline string
  deadline_normalized: string | null; // ISO 8601 resolved date
  deadline_type: "explicit" | "implicit" | "none";
  
  status: CommitmentStatus;
  resolved_at: string | null;        // When it was marked resolved
  resolved_message_id: string | null; // Which email resolved it
  resolution_confidence: number | null;
  
  extraction_confidence: number;     // 0.0–1.0 from Claude
  urgency_score: number;             // Computed, see §11
  
  notes: string | null;              // User-added notes
  tags: string[];                    // User-added tags
}

type CommitmentType = "deliver" | "respond" | "schedule" | "review" | "other";
type CommitmentStatus = "open" | "resolved" | "overdue" | "uncertain" | "dismissed";
```

### SyncState

```typescript
// Tracks incremental sync progress per Gmail account
interface SyncState {
  account_email: string;
  last_sync_at: string;           // ISO 8601
  last_history_id: string;        // Gmail history ID for incremental sync
  total_emails_processed: number;
  total_commitments_extracted: number;
}
```

### ExtractionRun

```typescript
// Log of each extraction run for debugging and eval
interface ExtractionRun {
  id: string;
  started_at: string;
  completed_at: string;
  emails_processed: number;
  commitments_found: number;
  tokens_used: number;
  errors: ExtractionError[];
}
```

---

## 9. Gmail Integration

The server uses the Gmail MCP connector available at `https://gmail.mcp.claude.com/mcp`.

### Sync Strategy

Use **incremental sync** via Gmail's History API to avoid re-scanning the full inbox:

```
1. On first sync: fetch last N=500 sent emails + last N=200 received emails
2. On subsequent syncs: use Gmail historyId to fetch only new/changed messages
3. Cache raw email content in SQLite to avoid re-fetching for resolution detection
4. Rate limit: max 10 Gmail API calls per sync run, with 200ms delay between calls
```

### Email Scope

```
Scan:
- SENT emails: extract outbound commitments made by user
- INBOX emails: extract inbound commitments made to user

Skip:
- Newsletters (List-Unsubscribe header present)
- Automated emails (no-reply@, noreply@, do-not-reply@)
- Calendar notifications (X-Google-Calendar-Content-Type header)
- Emails with only attachments and no body text
```

### Thread Reconstruction

For resolution detection, reconstruct the full thread chronologically:

```
1. Fetch all messages in thread via Gmail threads.get
2. Sort by internalDate ascending
3. For each message, extract only the NEW content (strip quoted text)
4. Label each segment [ME] or [THEM] based on sender vs account email
5. Pass as structured context to resolution detection prompt
```

---

## 10. Resolution Detection

Resolution detection is a second-pass process that runs after extraction. It is intentionally conservative — false positives (marking something resolved that isn't) are worse than false negatives.

### Resolution Signals (in order of confidence)

| Signal | Example | Confidence Boost |
|--------|---------|-----------------|
| Explicit acknowledgment | "Thanks, got the doc!" | +0.4 |
| Completion language | "Sent!", "Done, see attached" | +0.35 |
| Attachment in later message | File attached matching commitment subject | +0.3 |
| Implicit acknowledgment | Thread continues on different topic | +0.15 |
| No reply for 30+ days | Thread went silent | +0.05 (mark UNCERTAIN) |

### Resolution Prompt

```
SYSTEM:
You are checking whether a commitment was fulfilled in a later email.

Commitment: "{normalized_commitment}"
Made by: {direction} on {email_date}

Subsequent emails in this thread (chronological):
{subsequent_thread_text}

Was this commitment fulfilled? Respond ONLY with JSON:
{
  "resolved": true | false,
  "confidence": 0.0 - 1.0,
  "evidence": "brief quote or description of what resolved it",
  "resolved_in_message_id": "gmail message id or null"
}
```

---

## 11. Scoring & Prioritization

Each commitment gets an **urgency score** (0–100) used to rank the `get_commitments` list.

### Urgency Score Formula

```
urgency_score = deadline_score + staleness_score + direction_weight + confidence_weight

Where:

deadline_score:
  - Overdue: 50 points
  - Due today: 40 points
  - Due within 2 days: 30 points
  - Due within 7 days: 20 points
  - Due within 30 days: 10 points
  - No deadline: 5 points

staleness_score (days since email with no resolution):
  - 0–3 days: 0 points
  - 4–7 days: 5 points
  - 8–14 days: 10 points
  - 15–30 days: 15 points
  - 30+ days: 20 points

direction_weight:
  - outbound (you owe): +10 points
  - inbound (they owe you): +5 points

confidence_weight:
  - extraction_confidence > 0.9: +5 points
  - extraction_confidence 0.7–0.9: +2 points
  - extraction_confidence < 0.7: 0 points

Cap total at 100.
```

---

## 12. Storage & State Management

### SQLite Schema

```sql
-- Main commitments table
CREATE TABLE commitments (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  extracted_at TEXT NOT NULL,
  email_date TEXT NOT NULL,
  text TEXT NOT NULL,
  normalized TEXT NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('outbound','inbound')),
  commitment_type TEXT NOT NULL,
  counterparty_email TEXT NOT NULL,
  counterparty_name TEXT,
  deadline_raw TEXT,
  deadline_normalized TEXT,
  deadline_type TEXT NOT NULL DEFAULT 'none',
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved','overdue','uncertain','dismissed')),
  resolved_at TEXT,
  resolved_message_id TEXT,
  resolution_confidence REAL,
  extraction_confidence REAL NOT NULL,
  urgency_score INTEGER NOT NULL DEFAULT 0,
  notes TEXT,
  tags TEXT DEFAULT '[]',   -- JSON array stored as text
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Sync state per account
CREATE TABLE sync_state (
  account_email TEXT PRIMARY KEY,
  last_sync_at TEXT NOT NULL,
  last_history_id TEXT NOT NULL,
  total_emails_processed INTEGER DEFAULT 0,
  total_commitments_extracted INTEGER DEFAULT 0
);

-- Raw email cache for thread reconstruction
CREATE TABLE email_cache (
  message_id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  raw_content TEXT NOT NULL,
  sender_email TEXT NOT NULL,
  subject TEXT,
  date TEXT NOT NULL,
  cached_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Extraction run logs for observability
CREATE TABLE extraction_runs (
  id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  emails_processed INTEGER DEFAULT 0,
  commitments_found INTEGER DEFAULT 0,
  tokens_used INTEGER DEFAULT 0,
  errors TEXT DEFAULT '[]'  -- JSON array
);

-- Indexes for common query patterns
CREATE INDEX idx_commitments_status ON commitments(status);
CREATE INDEX idx_commitments_direction ON commitments(direction);
CREATE INDEX idx_commitments_counterparty ON commitments(counterparty_email);
CREATE INDEX idx_commitments_deadline ON commitments(deadline_normalized);
CREATE INDEX idx_commitments_urgency ON commitments(urgency_score DESC);
CREATE INDEX idx_email_cache_thread ON email_cache(thread_id);
```

### Caching Strategy

```
- Raw email content: cached indefinitely (emails don't change)
- Urgency scores: recomputed on every get_commitments call (deadlines move relative to now)
- Resolution status: re-checked on sync if status is OPEN and thread has new messages
```

---

## 13. Evaluation & Accuracy

This section is critical for a portfolio project — it shows you treat this like a real ML system, not a vibe-coded demo.

### Eval Dataset Construction

Build a labeled dataset of 200 emails:

```
- 50 emails with zero commitments (test false positive rate)
- 50 emails with 1 clear outbound commitment
- 50 emails with 1 clear inbound commitment
- 30 emails with 2–3 mixed commitments
- 20 "hard" emails with vague/implicit language
```

Label each email manually with ground truth commitments following the schema in §8.

### Metrics

```
Precision = True Positives / (True Positives + False Positives)
Recall    = True Positives / (True Positives + False Negatives)
F1        = 2 * (Precision * Recall) / (Precision + Recall)

Target:
  - Precision: ≥ 0.85  (we'd rather miss than falsely flag)
  - Recall:    ≥ 0.75
  - F1:        ≥ 0.80

Deadline accuracy (when deadline exists in ground truth):
  - Exact match: ≥ 70%
  - ±1 day: ≥ 85%

Resolution detection:
  - Precision: ≥ 0.90  (conservative — false "resolved" is bad UX)
  - Recall:    ≥ 0.65
```

### Eval Runner MCP Tool (Bonus)

Expose a `run_eval` tool that:
1. Runs extraction over the labeled dataset
2. Computes precision/recall/F1
3. Returns a breakdown by commitment type and direction
4. Diffs results against a baseline run

This makes the eval story visible to any hiring manager who plays with the tool.

---

## 14. API Reference

### Tool: `sync_emails`

Pulls new emails from Gmail and runs the extraction pipeline.

**Input:**
```json
{
  "max_emails": 100,        // optional, default 100, max 500
  "full_resync": false      // optional, re-scans all mail (slow)
}
```

**Output:**
```json
{
  "emails_processed": 47,
  "new_commitments": 12,
  "resolved_detected": 3,
  "tokens_used": 8420,
  "sync_duration_ms": 4200
}
```

---

### Tool: `get_commitments`

Returns a filtered, sorted list of commitments.

**Input:**
```json
{
  "status": "open",             // open | resolved | overdue | all
  "direction": "outbound",      // outbound | inbound | all
  "counterparty": "email",      // filter by person
  "limit": 20,                  // default 20
  "sort_by": "urgency_score"    // urgency_score | deadline | extracted_at
}
```

**Output:**
```json
{
  "commitments": [Commitment],
  "total": 47,
  "returned": 20
}
```

---

### Tool: `get_summary`

Returns high-level commitment stats.

**Output:**
```json
{
  "open_outbound": 14,
  "open_inbound": 8,
  "overdue": 3,
  "resolved_last_7_days": 11,
  "top_counterparties": [
    { "email": "boss@company.com", "open_count": 4 }
  ],
  "next_deadline": {
    "commitment_id": "...",
    "normalized": "Send Q2 report to finance team",
    "deadline": "2026-03-28T17:00:00Z"
  }
}
```

---

### Tool: `mark_resolved`

**Input:**
```json
{
  "commitment_id": "uuid",
  "notes": "Sent the doc at 3pm"  // optional
}
```

**Output:**
```json
{
  "success": true,
  "commitment": Commitment
}
```

---

## 15. Code Standards

All code in this project must follow these standards. These are requirements, not suggestions — the project will be reviewed as a portfolio artifact.

### Comments

Every file, class, and non-trivial function must have a comment explaining **what it does and why**, not just what the code literally says.

```typescript
// ✅ GOOD — explains purpose and non-obvious behavior
/**
 * Strips quoted/forwarded text from an email body.
 * 
 * Gmail includes previous messages in the thread body by default.
 * Without this step, the same commitment gets extracted N times
 * (once per reply that quotes it), causing duplicate entries.
 * 
 * Detection heuristics (in order):
 *   1. Gmail's native "-- Original Message --" separator
 *   2. Lines starting with ">" (standard quote prefix)
 *   3. "On [date], [name] wrote:" patterns
 *   4. Signature blocks ("-- ", "Best,", "Thanks,")
 */
function stripQuotedText(body: string): string { ... }

// ❌ BAD — obvious from the code itself
// Loop through emails
for (const email of emails) { ... }
```

### Module Structure

```
src/
  server.ts          # MCP server entry point — registers all tools, handles transport
  tools/
    sync.ts          # sync_emails tool — orchestrates the full extraction pipeline
    query.ts         # get_commitments, get_summary, get_overdue — read tools
    mutate.ts        # mark_resolved, add_tags — write tools
    eval.ts          # run_eval tool — accuracy measurement
  extraction/
    preprocess.ts    # Email cleaning: strip quotes, signatures, HTML
    extract.ts       # Stage 2: Claude API call for commitment detection
    deadline.ts      # Stage 3: Deadline normalization to ISO dates
    deduplicate.ts   # Stage 4: Embedding-based dedup across thread
    resolve.ts       # Stage 5: Resolution detection in subsequent emails
  gmail/
    client.ts        # Gmail MCP client wrapper — thin abstraction over MCP calls
    sync.ts          # Incremental sync logic using historyId
    cache.ts         # SQLite caching for raw email content
  db/
    schema.ts        # SQLite schema definitions and migrations
    commitments.ts   # Commitment CRUD operations
    sync_state.ts    # Sync state reads/writes
  scoring/
    urgency.ts       # Urgency score computation formula
  prompts/
    extraction.ts    # Extraction prompt template — versioned
    resolution.ts    # Resolution detection prompt template — versioned
  types/
    commitment.ts    # All TypeScript interfaces and types
  utils/
    logger.ts        # Structured logger (JSON output for prod, pretty for dev)
    retry.ts         # Exponential backoff retry wrapper for API calls
    tokens.ts        # Token counting utility for cost tracking
```

### Prompt Versioning

All prompts live in `src/prompts/` and are versioned:

```typescript
// src/prompts/extraction.ts

/**
 * Extraction prompt — v3
 * 
 * Changelog:
 *   v3: Added confidence threshold rule (< 0.6 = exclude). Reduced false
 *       positives on pleasantries by 23% vs v2 in eval.
 *   v2: Added [ME]/[THEM] tagging for direction classification
 *   v1: Initial version
 */
export const EXTRACTION_PROMPT_V3 = `...`;
export const CURRENT_EXTRACTION_PROMPT = EXTRACTION_PROMPT_V3;
```

### Error Handling

All MCP tool handlers must return structured errors, never throw raw exceptions to the client:

```typescript
// Every tool handler wraps in try/catch and returns structured response
try {
  const result = await extractCommitments(email);
  return { success: true, data: result };
} catch (error) {
  logger.error("Extraction failed", { email_id: email.id, error });
  return {
    success: false,
    error: {
      code: "EXTRACTION_FAILED",
      message: "Failed to extract commitments from email",
      details: error instanceof Error ? error.message : String(error)
    }
  };
}
```

### Logging

Use structured JSON logging throughout. Every extraction run should be traceable:

```typescript
logger.info("extraction.started", {
  run_id: runId,
  email_id: email.id,
  thread_id: email.threadId,
  token_estimate: tokenCount
});

logger.info("extraction.completed", {
  run_id: runId,
  commitments_found: commitments.length,
  tokens_used: tokensUsed,
  duration_ms: Date.now() - startTime
});
```

---

## 16. Error Handling

| Error Scenario | Behavior |
|---------------|----------|
| Gmail API rate limit hit | Exponential backoff, max 3 retries, then skip email and log |
| Claude API timeout | Retry once after 2s, then skip email and mark as pending |
| Invalid JSON from Claude | Retry with explicit JSON schema reminder in prompt, then skip |
| Email body too long | Truncate to 4,000 tokens with a note in the prompt |
| Duplicate commitment detected | Keep existing, log dedup event, do not insert |
| SQLite write failure | Log error, return partial results, do not crash server |
| Thread not found in cache | Re-fetch from Gmail, cache, then proceed |

---

## 17. Testing Strategy

### Unit Tests

```
extraction/preprocess.ts     — Test quote stripping on 20 real email patterns
extraction/deadline.ts       — Test deadline normalization on 50 date expressions
extraction/deduplicate.ts    — Test similarity threshold on known duplicate pairs
scoring/urgency.ts           — Test score formula against expected outputs
```

### Integration Tests

```
Full pipeline test on 10 labeled emails — check extraction output matches ground truth
Gmail sync test using a test Gmail account with seeded emails
Resolution detection test on 5 threads with known resolved/unresolved commitments
```

### Eval Pipeline (see §13)

```
npm run eval              → runs full eval on labeled dataset
npm run eval:diff         → diffs current vs baseline metrics
npm run eval:hard-cases   → runs only the "hard" 20 emails
```

---

## 18. Milestones

### Phase 1 — Core Extraction (Week 1–2)
- [ ] MCP server scaffolding (stdio transport)
- [ ] Gmail MCP client wrapper
- [ ] Email preprocessing pipeline
- [ ] Extraction prompt v1 + Claude API integration
- [ ] SQLite schema + commitment CRUD
- [ ] `sync_emails` and `get_commitments` tools working end-to-end

### Phase 2 — Accuracy & Resolution (Week 3)
- [ ] Deadline normalization engine
- [ ] Deduplication via embeddings
- [ ] Resolution detection pipeline
- [ ] Urgency scoring
- [ ] Eval dataset construction + first eval run
- [ ] Prompt iteration based on eval results

### Phase 3 — Polish & Portfolio (Week 4)
- [ ] SSE transport for hosted deployment
- [ ] All 8 MCP tools complete
- [ ] `run_eval` tool exposed via MCP
- [ ] Full code comments and README
- [ ] Structured logging + extraction run history
- [ ] Demo video / write-up for portfolio

---

## 19. Open Questions

| Question | Owner | Status |
|----------|-------|--------|
| Should we embed commitment text for semantic search, or is full-text enough? | Engineer | Open |
| What's the right staleness threshold for auto-marking as UNCERTAIN? | Product | Open |
| How do we handle commitments where the counterparty is a mailing list, not an individual? | Engineer | Open |
| Should resolution detection re-run on all open commitments on every sync, or only threads with new messages? | Engineer | Decided: only threads with new messages (performance) |
| Do we need to handle forwarded email chains separately from inline replies? | Engineer | Open |

---

---

## 20. Agent Implementation Guide

> **This section is written directly to the implementing agent.**
> You are building the Email Commitment Extractor MCP server described in this PRD.
> Read this entire section before writing a single line of code.
> Follow the task order exactly. Do not skip ahead. Do not assume.

---

### Your Role

You are a senior TypeScript engineer implementing this project from scratch. Your output will be reviewed as a portfolio artifact by AI engineering hiring managers. Code quality, comments, and structure matter as much as functionality.

Every file you write must:
- Have a top-of-file JSDoc comment explaining what the module does and why it exists
- Have JSDoc comments on every exported function explaining parameters, return values, and non-obvious behavior
- Use TypeScript strictly — no `any` types unless unavoidable and explicitly justified in a comment
- Handle errors explicitly — no unhandled promise rejections, no silent failures

---

### Pre-Implementation Decisions

The Open Questions in §19 are resolved here. Do not ask about these — treat them as decided:

| Question | Decision |
|----------|----------|
| Embed commitment text for semantic search? | No for v1. Use SQLite FTS5 full-text search. Add embeddings in v2. |
| Staleness threshold for UNCERTAIN? | 21 days with no thread activity → mark UNCERTAIN |
| Counterparty is a mailing list? | Extract commitment but set `counterparty_email` to the list address; set `counterparty_name` to the list name if detectable. Do not skip. |
| Resolution detection frequency? | Only re-run on threads that have received new messages since last sync. Use `last_activity_at` column on email cache to gate this. |
| Forwarded chains vs inline replies? | Treat forwarded chains as separate threads. If a forwarded message contains `---------- Forwarded message ---------`, strip everything below that line before extraction. |

---

### Environment Setup

Before writing any code, set up the project structure by running these commands in order:

```bash
# 1. Initialize the project
mkdir email-commitment-extractor && cd email-commitment-extractor
npm init -y

# 2. Install runtime dependencies
npm install @modelcontextprotocol/sdk zod better-sqlite3 anthropic

# 3. Install dev dependencies
npm install -D typescript @types/node @types/better-sqlite3 tsx vitest

# 4. Initialize TypeScript
npx tsc --init --strict --target ES2022 --module NodeNext --moduleResolution NodeNext

# 5. Create the full directory structure before writing any files
mkdir -p src/{tools,extraction,gmail,db,scoring,prompts,types,utils}
mkdir -p tests/{unit,integration}
mkdir -p eval/{dataset,results}
```

**Validation checkpoint:** Run `ls -R src/` and confirm all directories exist before continuing.

---

### Implementation Order

Follow this exact sequence. Each task has a validation checkpoint you must pass before moving to the next task. Do not proceed if a checkpoint fails — fix the issue first.

---

#### TASK 1 — Types & Interfaces
**File:** `src/types/commitment.ts`

Write all TypeScript interfaces from §8 of this PRD. Add one additional field to `Commitment` not in the original schema: `last_activity_at: string` (ISO 8601 timestamp of the most recent email in the thread — used for staleness scoring and resolution re-check gating).

Also define these utility types in the same file:

```typescript
// Result type — use this instead of throwing errors in business logic
type Result<T> = { success: true; data: T } | { success: false; error: AppError };

interface AppError {
  code: string;       // e.g. "EXTRACTION_FAILED", "DB_WRITE_FAILED"
  message: string;    // human-readable
  details?: string;   // raw error message for logging
}
```

**Validation checkpoint:**
```bash
npx tsc --noEmit
# Must produce zero errors
```

---

#### TASK 2 — Logger
**File:** `src/utils/logger.ts`

Write a structured logger that:
- In `NODE_ENV=development`: outputs pretty-printed, colored lines to stderr
- In `NODE_ENV=production`: outputs JSON lines to stderr (never stdout — MCP uses stdout)
- Has methods: `logger.info(event, meta?)`, `logger.warn(event, meta?)`, `logger.error(event, meta?)`
- The `event` parameter is always a dot-namespaced string like `"extraction.started"` or `"gmail.sync.failed"`
- Always includes `timestamp` and `event` in every log line

```typescript
// Example usage — document this in the JSDoc
logger.info("extraction.completed", {
  run_id: "abc123",
  commitments_found: 5,
  duration_ms: 420
});
```

**Validation checkpoint:**
```typescript
// Add a temporary test at the bottom of the file, run it, then remove it
logger.info("test.event", { foo: "bar" });
logger.error("test.error", { details: "something went wrong" });
// Both lines must print to stderr without throwing
```

---

#### TASK 3 — Database Schema & Client
**Files:** `src/db/schema.ts`, `src/db/client.ts`, `src/db/commitments.ts`, `src/db/sync_state.ts`

**`src/db/schema.ts`** — Export the full SQL from §12 as a string constant `DB_SCHEMA`. Add the `last_activity_at` column to `email_cache` as decided in Task 1. Also add a `schema_version` table:

```sql
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**`src/db/client.ts`** — Create and export a singleton SQLite database instance. On initialization:
1. Run `PRAGMA journal_mode = WAL` (better concurrent read performance)
2. Run `PRAGMA foreign_keys = ON`
3. Apply schema if not already applied (check `schema_version` table)
4. Log `"db.initialized"` with the schema version

**`src/db/commitments.ts`** — Export these functions:
- `insertCommitment(db, commitment: Omit<Commitment, 'created_at' | 'updated_at'>): Result<Commitment>`
- `getCommitments(db, filters: CommitmentFilters): Result<Commitment[]>`
- `updateCommitmentStatus(db, id: string, status: CommitmentStatus, meta?: Partial<Commitment>): Result<Commitment>`
- `getCommitmentById(db, id: string): Result<Commitment | null>`
- `searchCommitments(db, query: string): Result<Commitment[]>` — use SQLite FTS5

**`src/db/sync_state.ts`** — Export:
- `getSyncState(db, accountEmail: string): Result<SyncState | null>`
- `upsertSyncState(db, state: SyncState): Result<SyncState>`

**Validation checkpoint:**
```typescript
// In a temporary test script, run:
const db = getDb();
const result = insertCommitment(db, { ...mockCommitment });
console.assert(result.success === true, "Insert should succeed");
const fetched = getCommitmentById(db, result.data.id);
console.assert(fetched.success && fetched.data?.id === result.data.id, "Fetch should return inserted record");
// Then delete the test script
```

---

#### TASK 4 — Retry Utility
**File:** `src/utils/retry.ts`

Write a generic `withRetry<T>` function:

```typescript
/**
 * Wraps an async function with exponential backoff retry logic.
 * 
 * Use this for all external API calls (Claude API, Gmail MCP) to handle
 * transient failures gracefully. Does NOT retry on 4xx errors (client errors
 * like invalid auth or bad request) — only on network errors and 5xx/429.
 *
 * @param fn - Async function to retry
 * @param options.maxAttempts - Max number of attempts (default: 3)
 * @param options.baseDelayMs - Base delay in ms, doubles each retry (default: 500)
 * @param options.shouldRetry - Optional predicate to determine if error is retryable
 */
async function withRetry<T>(
  fn: () => Promise<T>,
  options?: RetryOptions
): Promise<T>
```

**Validation checkpoint:**
```typescript
// Test that it retries exactly N times then throws
let attempts = 0;
try {
  await withRetry(() => { attempts++; throw new Error("fail"); }, { maxAttempts: 3 });
} catch {}
console.assert(attempts === 3, `Expected 3 attempts, got ${attempts}`);
```

---

#### TASK 5 — Prompts
**Files:** `src/prompts/extraction.ts`, `src/prompts/resolution.ts`

**`src/prompts/extraction.ts`** — Write the extraction prompt from §7 Stage 2 as a versioned constant. Export a function `buildExtractionPrompt(emailContent: string): { system: string; user: string }` that injects the email content. The function must validate that `emailContent` is not empty and not longer than 4,000 tokens (use a rough estimate of 4 chars per token).

**`src/prompts/resolution.ts`** — Write the resolution prompt from §10. Export `buildResolutionPrompt(commitment: Commitment, subsequentEmails: string): { system: string; user: string }`.

Both files must include version changelog comments as shown in §15 Code Standards.

**Validation checkpoint:**
```typescript
const prompt = buildExtractionPrompt("[ME] I'll send the report by Friday.\n[THEM] Great, thanks.");
console.assert(prompt.system.length > 0, "System prompt must not be empty");
console.assert(prompt.user.includes("[ME]"), "User prompt must include the email content");
```

---

#### TASK 6 — Email Preprocessing
**File:** `src/extraction/preprocess.ts`

Implement the preprocessing pipeline from §7 Stage 1. Export:

- `preprocessEmail(rawBody: string, senderEmail: string, accountEmail: string): PreprocessedEmail`

```typescript
interface PreprocessedEmail {
  content: string;        // cleaned body with [ME]/[THEM] tags
  wasStripped: boolean;   // true if quoted text was removed
  estimatedTokens: number;
  truncated: boolean;     // true if content was cut to 4,000 token limit
}
```

Write unit tests in `tests/unit/preprocess.test.ts` covering:
- Email with Gmail-style quoted reply ("> " lines)
- Email with "On [date], [name] wrote:" forwarded block
- Email with signature block ("-- \nBest,")
- Clean email with no quoted text (wasStripped should be false)
- Email longer than 4,000 tokens (truncated should be true)

**Validation checkpoint:**
```bash
npx vitest run tests/unit/preprocess.test.ts
# All tests must pass
```

---

#### TASK 7 — Deadline Normalization
**File:** `src/extraction/deadline.ts`

Implement the deadline normalization logic from §7 Stage 3. Export:

- `normalizeDeadline(raw: string | null, emailDate: string): NormalizedDeadline`

```typescript
interface NormalizedDeadline {
  iso: string | null;           // ISO 8601 date, or null if unparseable
  type: "explicit" | "implicit" | "none";
  confidence: number;           // 0.0–1.0 how confident we are in the parsed date
}
```

Cover all cases from the PRD: explicit dates, day-of-week references, named periods, implicit language, and null. Write unit tests in `tests/unit/deadline.test.ts` with at least 15 test cases.

**Validation checkpoint:**
```bash
npx vitest run tests/unit/deadline.test.ts
# All tests must pass
```

---

#### TASK 8 — Claude Extraction Client
**File:** `src/extraction/extract.ts`

Implement the Claude API call for commitment extraction. Export:

- `extractCommitmentsFromEmail(email: PreprocessedEmail, messageId: string, threadId: string, emailDate: string): Promise<Result<RawExtractedCommitment[]>>`

```typescript
// The raw shape returned by Claude before normalization
interface RawExtractedCommitment {
  text: string;
  normalized: string;
  direction: "outbound" | "inbound";
  confidence: number;
  deadline_raw: string | null;
  deadline_type: "explicit" | "implicit" | "none";
  commitment_type: CommitmentType;
  counterparty: string;
}
```

Requirements:
- Use `withRetry` for the API call
- Validate that Claude returns valid JSON — if parsing fails, retry once with an explicit JSON correction prompt before giving up
- Filter out any commitments with `confidence < 0.6` before returning
- Log `"extraction.api_call"` with token counts before and after
- Log `"extraction.parse_failed"` if JSON parsing fails

**Validation checkpoint:**
```typescript
// Call with a simple test email — do not mock, use the real API
const result = await extractCommitmentsFromEmail(
  { content: "[ME] I'll send the deck by Friday. [THEM] Perfect.", wasStripped: false, estimatedTokens: 20, truncated: false },
  "test-msg-id",
  "test-thread-id",
  new Date().toISOString()
);
console.assert(result.success === true, "Extraction must succeed");
console.assert(result.data.length >= 1, "Must find at least one commitment");
console.assert(result.data[0].direction === "outbound", "Must correctly classify direction");
```

---

#### TASK 9 — Deduplication
**File:** `src/extraction/deduplicate.ts`

Implement deduplication from §7 Stage 4. Because we are not using embeddings in v1, use a simpler but effective heuristic approach:

- Two commitments are duplicates if they share the same `thread_id`, same `direction`, and their `normalized` text has a Jaccard similarity > 0.7 on word tokens
- Export `deduplicateCommitments(incoming: RawExtractedCommitment[], existing: Commitment[]): RawExtractedCommitment[]`
- The function returns only the commitments from `incoming` that are NOT duplicates of anything in `existing`
- Include the Jaccard similarity implementation inline with a clear comment explaining the algorithm

**Validation checkpoint:**
```typescript
const existing = [{ normalized: "Send the Q2 report to finance", direction: "outbound", thread_id: "t1" }];
const incoming = [
  { normalized: "Send Q2 report to the finance team", direction: "outbound", thread_id: "t1" }, // duplicate
  { normalized: "Schedule a call with legal", direction: "outbound", thread_id: "t1" }           // not duplicate
];
const result = deduplicateCommitments(incoming, existing);
console.assert(result.length === 1, "Should keep only the non-duplicate");
console.assert(result[0].normalized.includes("legal"), "Should keep the legal call commitment");
```

---

#### TASK 10 — Resolution Detection
**File:** `src/extraction/resolve.ts`

Implement resolution detection from §10. Export:

- `detectResolution(commitment: Commitment, subsequentEmails: EmailSegment[]): Promise<Result<ResolutionResult>>`

```typescript
interface EmailSegment {
  message_id: string;
  sender_role: "ME" | "THEM";
  content: string;
  date: string;
}

interface ResolutionResult {
  resolved: boolean;
  confidence: number;
  evidence: string | null;
  resolved_message_id: string | null;
}
```

Requirements:
- Only call the Claude API if `subsequentEmails.length > 0` — if empty, return `{ resolved: false, confidence: 0, evidence: null, resolved_message_id: null }` immediately
- Use `withRetry` for the API call
- Threshold: only mark `resolved: true` if confidence >= 0.75 (per §10)
- Log `"resolution.detected"` when a resolution is found with evidence

**Validation checkpoint:**
```bash
npx tsc --noEmit
# Must produce zero errors on this file
```

---

#### TASK 11 — Urgency Scoring
**File:** `src/scoring/urgency.ts`

Implement the urgency score formula from §11 exactly. Export:

- `computeUrgencyScore(commitment: Commitment): number`

Write unit tests in `tests/unit/urgency.test.ts` covering every branch of the formula:
- Overdue commitment with high confidence (expect score near 100)
- Due today, outbound (expect score 50–65)
- No deadline, low confidence (expect score near 5)
- Inbound, due in 3 days (expect score 30–45)

**Validation checkpoint:**
```bash
npx vitest run tests/unit/urgency.test.ts
# All tests must pass
```

---

#### TASK 12 — Gmail Client
**File:** `src/gmail/client.ts`

Write a thin wrapper around the Gmail MCP connector. Export these functions:

- `fetchRecentEmails(maxResults: number): Promise<Result<GmailMessage[]>>`
- `fetchThread(threadId: string): Promise<Result<GmailThread>>`
- `fetchEmailsSinceHistoryId(historyId: string): Promise<Result<GmailMessage[]>>`

```typescript
interface GmailMessage {
  id: string;
  threadId: string;
  subject: string;
  from: string;
  to: string;
  date: string;         // ISO 8601
  body: string;         // plain text body
  hasAttachments: boolean;
}

interface GmailThread {
  id: string;
  messages: GmailMessage[];
}
```

Requirements:
- All functions must use `withRetry`
- Skip emails where `from` matches `/(no-reply|noreply|do-not-reply|mailer-daemon)/i`
- Skip emails where body is empty after stripping HTML
- Log `"gmail.fetch"` with message count on success
- Log `"gmail.skip"` with reason when an email is filtered out

**Validation checkpoint:**
```bash
npx tsc --noEmit
# Must produce zero errors
```

---

#### TASK 13 — Sync Pipeline
**File:** `src/gmail/sync.ts`

Orchestrates the full extraction pipeline. Export:

- `runSync(db: Database, options: SyncOptions): Promise<Result<SyncResult>>`

```typescript
interface SyncOptions {
  maxEmails: number;
  fullResync: boolean;
  accountEmail: string;
}

interface SyncResult {
  emails_processed: number;
  new_commitments: number;
  resolved_detected: number;
  tokens_used: number;
  sync_duration_ms: number;
  errors: AppError[];
}
```

The function must follow this exact sequence:
1. Load sync state from DB — if none exists, set `fullResync = true`
2. Fetch emails from Gmail (use history ID if incremental, fetch recent if full resync)
3. For each email:
   a. Check if already in email cache — skip if so (unless fullResync)
   b. Preprocess the email body
   c. Run extraction
   d. Deduplicate against existing commitments for this thread
   e. Normalize deadlines for each new commitment
   f. Compute urgency score for each new commitment
   g. Insert new commitments into DB
   h. Cache the raw email
4. After all emails: for each OPEN commitment whose thread has new messages, run resolution detection
5. Update sync state with new history ID and timestamp
6. Return SyncResult

Log `"sync.started"`, `"sync.email_processed"` (for each email), and `"sync.completed"` events.

**Validation checkpoint:**
```bash
npx tsc --noEmit
# Must produce zero errors
```

---

#### TASK 14 — MCP Tools
**Files:** `src/tools/sync.ts`, `src/tools/query.ts`, `src/tools/mutate.ts`

Implement all 8 MCP tools from §6 and §14. Each tool must:
- Use Zod schemas for input validation
- Return structured JSON (never raw error strings to the client)
- Log the tool call at start and completion with duration

**`src/tools/sync.ts`** — `sync_emails` tool

**`src/tools/query.ts`** — `get_commitments`, `get_commitment_detail`, `get_summary`, `get_inbound`, `get_overdue`, `search_commitments` tools

**`src/tools/mutate.ts`** — `mark_resolved` tool

**Validation checkpoint:**
```bash
npx tsc --noEmit
# Must produce zero errors on all tool files
```

---

#### TASK 15 — MCP Server Entry Point
**File:** `src/server.ts`

Wire everything together. This file:
1. Reads `--transport` flag from `process.argv` (default: `stdio`)
2. Creates the MCP server with metadata from §6
3. Registers all tools from Task 14
4. Connects to the appropriate transport
5. Logs `"server.started"` with transport type and version

```typescript
// Example startup log
logger.info("server.started", {
  transport: "stdio",
  version: "1.0.0",
  tools_registered: 8
});
```

**Final validation checkpoint:**
```bash
# Run the server in stdio mode — it should start without errors
npx tsx src/server.ts --transport stdio
# You should see: server.started log line
# Press Ctrl+C to exit

# Type-check the entire project
npx tsc --noEmit
# Must produce zero errors across all files
```

---

### Self-Check Checklist

Before declaring the implementation complete, run through every item on this list. Do not skip any item. If any item fails, fix it before continuing.

**Code Quality**
- [ ] Every file has a top-of-file JSDoc comment explaining what it does and why
- [ ] Every exported function has a JSDoc comment with `@param` and `@returns`
- [ ] No `any` types without a justifying comment
- [ ] No `console.log` — all logging goes through `src/utils/logger.ts`
- [ ] No unhandled promise rejections (all async calls have try/catch or `.catch()`)

**TypeScript**
- [ ] `npx tsc --noEmit` produces zero errors
- [ ] All interfaces are defined in `src/types/commitment.ts` and imported from there

**Tests**
- [ ] `npx vitest run tests/unit/` passes with zero failures
- [ ] Preprocessing tests cover all 5 cases from Task 6
- [ ] Deadline normalization tests cover at least 15 cases from Task 7
- [ ] Urgency scoring tests cover all 4 branches from Task 11

**Functionality**
- [ ] `sync_emails` tool runs end-to-end without throwing
- [ ] `get_commitments` returns results sorted by urgency_score descending
- [ ] `get_summary` returns all required fields including `next_deadline`
- [ ] `mark_resolved` correctly updates status and sets `resolved_at`
- [ ] Deduplication prevents the same commitment from being inserted twice

**Observability**
- [ ] Every sync run creates an `extraction_runs` record in DB
- [ ] Every Claude API call logs token usage
- [ ] All errors are logged with `logger.error` before being returned as `Result` failures

**Error Handling**
- [ ] All 7 error scenarios from §16 are handled (not just the happy path)
- [ ] No MCP tool ever throws an unhandled exception to the client

**README**
- [ ] `README.md` exists with: project description, setup instructions, how to connect to Claude Desktop/Claude.ai, example Claude conversation showing the tools in use, and eval results from a real run

---

### Prompt for Hiring Manager Demo

Once built, use this prompt to demo the server to a hiring manager:

```
I've connected the Email Commitment Extractor MCP server. 

1. Run a sync on my last 50 emails
2. Show me a summary of open commitments
3. What's the most urgent thing I owe someone right now?
4. Are there any commitments others made to me that are overdue?
5. Mark commitment [id] as resolved
```

This sequence exercises all major code paths and tells a clear story in under 2 minutes.

---

*End of Agent Implementation Guide — PRD v1.0.0 complete*
