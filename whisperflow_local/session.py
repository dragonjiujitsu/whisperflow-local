"""Typed, main-thread-owned dictation session state.

Workers receive a session id and the shared cancellation event.  They may
produce outcomes, but only the controller's main-thread event handler advances
the active session.  Results for an older id are deliberately ignored.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum, auto
from threading import Event


class SessionPhase(Enum):
    IDLE = auto()
    STARTING = auto()
    RECORDING = auto()
    FINALIZING = auto()
    TRANSCRIBING = auto()
    CLEANING = auto()
    INSERTING = auto()
    READY = auto()
    CANCELLED = auto()
    ERROR = auto()


class SessionEvent(Enum):
    RECORDING_STARTED = auto()
    RECORDING_STOPPED = auto()
    TRANSCRIPTION_STARTED = auto()
    TRANSCRIPTION_FINISHED = auto()
    CLEANUP_FINISHED = auto()
    INSERTION_FINISHED = auto()
    CANCELLED = auto()


_TRANSITIONS: dict[tuple[SessionPhase, SessionEvent], SessionPhase] = {
    (SessionPhase.STARTING, SessionEvent.RECORDING_STARTED): SessionPhase.RECORDING,
    (SessionPhase.RECORDING, SessionEvent.RECORDING_STOPPED): SessionPhase.FINALIZING,
    (SessionPhase.FINALIZING, SessionEvent.TRANSCRIPTION_STARTED): SessionPhase.TRANSCRIBING,
    (SessionPhase.TRANSCRIBING, SessionEvent.TRANSCRIPTION_FINISHED): SessionPhase.CLEANING,
    (SessionPhase.CLEANING, SessionEvent.CLEANUP_FINISHED): SessionPhase.INSERTING,
    (SessionPhase.INSERTING, SessionEvent.INSERTION_FINISHED): SessionPhase.READY,
}

_CANCELLABLE = {
    SessionPhase.STARTING,
    SessionPhase.RECORDING,
    SessionPhase.FINALIZING,
    SessionPhase.TRANSCRIBING,
    SessionPhase.CLEANING,
    SessionPhase.INSERTING,
}

_TERMINAL = {SessionPhase.READY, SessionPhase.CANCELLED, SessionPhase.ERROR}


@dataclass(frozen=True)
class DictationSession:
    session_id: int
    phase: SessionPhase
    cancelled: Event = field(compare=False, repr=False)
    reason: str = ""


class SessionReducer:
    """Own the active session and reject events from obsolete workers."""

    def __init__(self) -> None:
        self._next_id = 0
        self._current = DictationSession(0, SessionPhase.IDLE, Event())

    @property
    def current(self) -> DictationSession:
        return self._current

    def start(self) -> DictationSession:
        if self._current.phase not in {
            SessionPhase.IDLE,
            SessionPhase.READY,
            SessionPhase.CANCELLED,
            SessionPhase.ERROR,
        }:
            self._current.cancelled.set()
        self._next_id += 1
        self._current = DictationSession(
            self._next_id, SessionPhase.STARTING, Event()
        )
        return self._current

    def transition(
        self, session_id: int, event: SessionEvent
    ) -> DictationSession:
        if session_id != self._current.session_id:
            return self._current
        current = self._current
        if current.phase in _TERMINAL:
            return current
        if event is SessionEvent.CANCELLED:
            if current.phase not in _CANCELLABLE:
                raise ValueError(
                    f"cannot cancel session in {current.phase.name.lower()}"
                )
            current.cancelled.set()
            self._current = replace(
                current, phase=SessionPhase.CANCELLED, reason="cancelled"
            )
            return self._current
        next_phase = _TRANSITIONS.get((current.phase, event))
        if next_phase is None:
            raise ValueError(
                f"illegal session transition: {current.phase.name.lower()} "
                f"+ {event.name.lower()}"
            )
        self._current = replace(current, phase=next_phase)
        return self._current

    def fail(self, session_id: int, reason: str) -> DictationSession:
        if session_id != self._current.session_id:
            return self._current
        if self._current.phase in _TERMINAL:
            return self._current
        self._current.cancelled.set()
        self._current = replace(
            self._current, phase=SessionPhase.ERROR, reason=reason
        )
        return self._current

    def is_active(self, session_id: int) -> bool:
        return (
            session_id == self._current.session_id
            and self._current.phase not in _TERMINAL
            and not self._current.cancelled.is_set()
        )
