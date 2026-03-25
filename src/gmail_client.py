import os
import base64
import re
from typing import List, Optional, Dict, Any
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

class GmailClient:
    def __init__(self, credentials_path: str = "credentials.json", token_path: str = "token.json"):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.creds = self._authenticate()
        self.service = build('gmail', 'v1', credentials=self.creds)
        self.user_email = self._get_user_email()

    def _authenticate(self):
        creds = None
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(f"Gmail credentials not found at {self.credentials_path}")
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(self.token_path, 'w') as token:
                token.write(creds.to_json())
        return creds

    def _get_user_email(self) -> str:
        profile = self.service.users().getProfile(userId='me').execute()
        return profile.get('emailAddress')

    def get_messages(self, query: str = "", max_results: int = 100) -> List[Dict[str, Any]]:
        try:
            results = self.service.users().messages().list(userId='me', q=query, maxResults=max_results).execute()
            return results.get('messages', [])
        except HttpError as error:
            print(f"An error occurred: {error}")
            return []

    def get_message_detail(self, message_id: str) -> Dict[str, Any]:
        try:
            return self.service.users().messages().get(userId='me', id=message_id, format='full').execute()
        except HttpError as error:
            print(f"An error occurred: {error}")
            return {}

    def get_thread(self, thread_id: str) -> Dict[str, Any]:
        try:
            return self.service.users().threads().get(userId='me', id=thread_id).execute()
        except HttpError as error:
            print(f"An error occurred: {error}")
            return {}

    def get_history(self, start_history_id: str) -> List[Dict[str, Any]]:
        try:
            results = self.service.users().history().list(userId='me', startHistoryId=start_history_id).execute()
            return results.get('history', [])
        except HttpError as error:
            # If history ID is too old, we might need to do a full sync
            print(f"History ID too old or error: {error}")
            return []

    def extract_body_text(self, message_payload: Dict[str, Any]) -> str:
        """Extracts and cleans body text from message payload."""
        body = ""
        if 'parts' in message_payload:
            for part in message_payload['parts']:
                if part['mimeType'] == 'text/plain':
                    data = part['body'].get('data')
                    if data:
                        body += base64.urlsafe_b64decode(data).decode('utf-8')
                elif part['mimeType'] == 'multipart/alternative':
                    body += self.extract_body_text(part)
        else:
            data = message_payload['body'].get('data')
            if data:
                body = base64.urlsafe_b64decode(data).decode('utf-8')
        
        return self._clean_text(body)

    def has_attachments(self, message_payload: Dict[str, Any]) -> bool:
        """Recursively checks if the message payload contains attachments."""
        if 'filename' in message_payload and message_payload['filename']:
            return True
        if 'parts' in message_payload:
            for part in message_payload['parts']:
                if self.has_attachments(part):
                    return True
        return False

    def _clean_text(self, text: str) -> str:
        """Strips signatures, quoted text, and normalizes whitespace."""
        # 1. Strip quoted text (common markers like ">", "On ... wrote:")
        text = re.sub(r'(?m)^>.*$', '', text)
        text = re.sub(r'(?s)On\s+.*wrote:.*', '', text)
        
        # 2. Strip signatures (detected via heuristics: "-- ", "Best,", "Thanks,")
        sig_markers = [r'--\s*$', r'Best,.*', r'Thanks,.*', r'Regards,.*', r'Sincerely,.*']
        for marker in sig_markers:
            text = re.split(marker, text, flags=re.IGNORECASE | re.MULTILINE)[0]
        
        # 3. Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text

    def parse_message_headers(self, message: Dict[str, Any]) -> Dict[str, str]:
        headers = message.get('payload', {}).get('headers', [])
        result = {}
        for header in headers:
            name = header.get('name').lower()
            if name in ['from', 'to', 'subject', 'date']:
                result[name] = header.get('value')
        return result
