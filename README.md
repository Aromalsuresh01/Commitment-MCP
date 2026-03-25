# Email Commitment Extractor

An MCP (Model Context Protocol) server that automatically extracts, tracks, and manages commitments from your Gmail account.

## 🚀 Overview

**Email Commitment Extractor** solves the "lost in email" problem by scanning your Gmail sent and received messages to identify things you promised to do, deadlines you set, and things others promised you. It surfaces these as a structured, ranked, real-time tracker so nothing falls through the cracks.

Built as an **MCP Server**, it allows AI agents (like Claude) to conversationally interact with your commitments, providing a powerful interface for personal productivity.

## ✨ Features

- **Automated Extraction**: Uses Claude-3.5-Sonnet to identify explicit and implicit commitments from natural language email text.
- **Bi-directional Tracking**: Tracks both *outbound* (what you owe others) and *inbound* (what others owe you) obligations.
- **Deadline Detection**: Normalizes relative deadlines (e.g., "by EOD Friday", "next week") into concrete timestamps.
- **Resolution Tracking**: Automatically detects if a commitment has been fulfilled in subsequent emails in the same thread.
- **Smart Prioritization**: Computes an urgency score (0-100) based on deadlines, staleness, and commitment direction.
- **Conversational Interface**: Exposes tools via MCP for seamless integration with AI agents.

## 🛠️ How It Works

The system operates in a multi-stage pipeline:

1.  **Sync**: Connects to Gmail API to fetch new messages.
2.  **Preprocessing**: Cleans email text by stripping signatures, quoted replies, and normalizing whitespace.
3.  **Extraction**: Sends cleaned text to Claude to extract structured commitment data.
4.  **Resolution Pass**: Analyzes thread history to check if previously extracted commitments have been resolved.
5.  **State Management**: Stores all data in a local SQLite database for fast retrieval and persistence.

## 📦 Installation

### Prerequisites

- Python 3.10+
- Anthropic API Key
- Google Cloud Project with Gmail API enabled (and `credentials.json` downloaded)

### Setup

1.  Clone the repository:
    ```bash
    git clone https://github.com/yourusername/email-commitment-extractor.git
    cd email-commitment-extractor
    ```

2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

3.  Configure environment variables:
    ```bash
    cp .env.example .env
    # Edit .env with your ANTHROPIC_API_KEY
    ```

4.  Place your `credentials.json` in the project root.

## 🚀 Usage

### Running the Server

To start the MCP server in stdio mode:

```bash
python -m src.server
```

### Available MCP Tools

| Tool | Description |
| :--- | :--- |
| `sync_emails` | Pull new emails and extract commitments. |
| `get_commitments` | Retrieve a filtered and sorted list of commitments. |
| `get_commitment_detail` | Get full details and context for a specific commitment. |
| `mark_resolved` | Manually mark a commitment as done. |
| `get_summary` | Get high-level statistics on open/overdue items. |

## 🧪 Testing

Run the test suite to verify extraction logic:

```bash
python -m unittest discover tests
```

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
