"""
Wave Surf — Session Store
Manages per-user browser sessions with isolated Playwright contexts.
"""

import json
from typing import Optional
from datetime import datetime

class SessionStore:
    def __init__(self):
        self.sessions = {}  # user_id -> session data
    
    def create_session(self, user_id: str, browser_context=None):
        """Create a new isolated browser session for a user."""
        self.sessions[user_id] = {
            "user_id": user_id,
            "context": browser_context,
            "created_at": datetime.utcnow().isoformat(),
            "last_activity": datetime.utcnow().isoformat(),
            "tabs": [{"id": "tab_1", "url": "about:blank", "title": "New Tab"}],
            "active_tab": "tab_1",
            "history": [],
            "history_index": -1
        }
        return self.sessions[user_id]
    
    def get_session(self, user_id: str):
        """Get or create a session for a user."""
        if user_id not in self.sessions:
            self.create_session(user_id)
        self.sessions[user_id]["last_activity"] = datetime.utcnow().isoformat()
        return self.sessions[user_id]
    
    def destroy_session(self, user_id: str):
        """Destroy a user's session."""
        if user_id in self.sessions:
            session = self.sessions[user_id]
            if session.get("context"):
                try:
                    # Close the browser context
                    asyncio.get_event_loop().run_until_complete(session["context"].close())
                except:
                    pass
            del self.sessions[user_id]
            return True
        return False
    
    def add_to_history(self, user_id: str, url: str):
        """Add a URL to the user's history."""
        session = self.get_session(user_id)
        # Truncate forward history if navigating from a non-latest position
        if session["history_index"] < len(session["history"]) - 1:
            session["history"] = session["history"][:session["history_index"] + 1]
        session["history"].append({
            "url": url,
            "visited": datetime.utcnow().isoformat()
        })
        session["history_index"] = len(session["history"]) - 1
    
    def get_history(self, user_id: str, limit: int = 50):
        """Get the user's browsing history."""
        session = self.get_session(user_id)
        return session["history"][-limit:]
    
    def can_go_back(self, user_id: str):
        session = self.get_session(user_id)
        return session["history_index"] > 0
    
    def can_go_forward(self, user_id: str):
        session = self.get_session(user_id)
        return session["history_index"] < len(session["history"]) - 1

# Global session store
store = SessionStore()
