"""In-memory session management for uploaded datasets."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

ProfileDict = dict[str, Any]
SessionMetadata = dict[str, str | datetime]


@dataclass
class DatasetSession:
    """Represents one uploaded dataset and its associated metadata."""

    session_id: str
    filename: str
    uploaded_at: datetime
    dataframe: pd.DataFrame
    dataset_profile: ProfileDict
    last_accessed: datetime


class DatasetSessionManager:
    """Thread-safe in-memory store for uploaded dataset sessions."""

    def __init__(self) -> None:
        """Initialize an empty session registry."""
        self._sessions: dict[str, DatasetSession] = {}
        self._lock = threading.RLock()

    def create_session(
        self,
        dataframe: pd.DataFrame,
        filename: str,
        profile: ProfileDict,
    ) -> str:
        """Create and store a new dataset session.

        Args:
            dataframe: Parsed dataset to keep in memory for the session.
            filename: Original uploaded filename for display and auditing.
            profile: JSON-serializable dataset profile from ``DatasetProfiler``.

        Returns:
            The newly generated session identifier.

        Raises:
            ValueError: If the dataframe is empty, filename is blank, or the
                profile is not a dictionary.
        """
        self._validate_dataframe(dataframe)
        normalized_filename = self._validate_filename(filename)
        self._validate_profile(profile)

        timestamp = self._utc_now()
        session_id = str(uuid.uuid4())
        session = DatasetSession(
            session_id=session_id,
            filename=normalized_filename,
            uploaded_at=timestamp,
            dataframe=dataframe,
            dataset_profile=profile,
            last_accessed=timestamp,
        )

        with self._lock:
            self._sessions[session_id] = session

        return session_id

    def get_session(self, session_id: str) -> DatasetSession:
        """Return a session and refresh its last-accessed timestamp.

        Args:
            session_id: Identifier of the session to retrieve.

        Returns:
            The stored ``DatasetSession`` instance.

        Raises:
            KeyError: If no session exists for the given identifier.
        """
        with self._lock:
            session = self._require_session(session_id)
            session.last_accessed = self._utc_now()
            return session

    def get_dataframe(self, session_id: str) -> pd.DataFrame:
        """Return the dataframe associated with a session.

        Args:
            session_id: Identifier of the session to retrieve.

        Returns:
            The stored Pandas dataframe.

        Raises:
            KeyError: If no session exists for the given identifier.
        """
        return self.get_session(session_id).dataframe

    def get_profile(self, session_id: str) -> ProfileDict:
        """Return the dataset profile associated with a session.

        Args:
            session_id: Identifier of the session to retrieve.

        Returns:
            The stored dataset profile dictionary.

        Raises:
            KeyError: If no session exists for the given identifier.
        """
        return self.get_session(session_id).dataset_profile

    def delete_session(self, session_id: str) -> bool:
        """Delete a session from memory.

        Args:
            session_id: Identifier of the session to delete.

        Returns:
            ``True`` if the session existed and was removed, otherwise ``False``.
        """
        with self._lock:
            if session_id not in self._sessions:
                return False
            del self._sessions[session_id]
            return True

    def list_sessions(self) -> list[SessionMetadata]:
        """Return lightweight metadata for all active sessions.

        Returns:
            A list of session metadata dictionaries. Dataframes are excluded.
        """
        with self._lock:
            return [
                {
                    "session_id": session.session_id,
                    "filename": session.filename,
                    "uploaded_at": session.uploaded_at,
                    "last_accessed": session.last_accessed,
                }
                for session in self._sessions.values()
            ]

    def cleanup_expired_sessions(self, timeout_minutes: int) -> int:
        """Remove sessions that have not been accessed within the timeout.

        Args:
            timeout_minutes: Inactivity threshold in minutes. Must be positive.

        Returns:
            The number of sessions removed.

        Raises:
            ValueError: If ``timeout_minutes`` is not positive.
        """
        if timeout_minutes <= 0:
            raise ValueError("timeout_minutes must be greater than zero.")

        cutoff = self._utc_now() - timedelta(minutes=timeout_minutes)

        with self._lock:
            expired_session_ids = [
                session_id
                for session_id, session in self._sessions.items()
                if session.last_accessed < cutoff
            ]
            for session_id in expired_session_ids:
                del self._sessions[session_id]

        return len(expired_session_ids)

    def _require_session(self, session_id: str) -> DatasetSession:
        """Return a session or raise if it does not exist.

        This helper must be called while ``self._lock`` is held.
        """
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"Session not found: {session_id}") from exc

    @staticmethod
    def _utc_now() -> datetime:
        """Return the current UTC timestamp."""
        return datetime.now(timezone.utc)

    @staticmethod
    def _validate_dataframe(dataframe: pd.DataFrame) -> None:
        """Ensure the dataframe contains data."""
        if dataframe.empty:
            raise ValueError("dataframe must not be empty.")

    @staticmethod
    def _validate_filename(filename: str) -> str:
        """Ensure the filename is present and normalized."""
        if filename is None:
            raise ValueError("filename must not be empty.")

        normalized = filename.strip()
        if not normalized:
            raise ValueError("filename must not be empty.")
        return normalized

    @staticmethod
    def _validate_profile(profile: ProfileDict) -> None:
        """Ensure the dataset profile is a usable dictionary."""
        if not isinstance(profile, dict):
            raise ValueError("profile must be a dictionary.")
        if not profile:
            raise ValueError("profile must not be empty.")
