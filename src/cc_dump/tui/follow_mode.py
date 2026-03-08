"""Follow-mode state machine and transitions.

// [LAW:one-source-of-truth] Follow transitions live in one module shared by TUI layers.
// [LAW:dataflow-not-control-flow] Transition + side effects are table-driven data.
"""

from dataclasses import dataclass
from enum import Enum
from snarfx import Observable, reaction


class FollowState(Enum):
    OFF = "off"
    ENGAGED = "engaged"
    ACTIVE = "active"


class FollowEvent(Enum):
    USER_SCROLL = "user_scroll"
    TOGGLE = "toggle"
    SCROLL_BOTTOM = "scroll_bottom"
    DEACTIVATE = "deactivate"


@dataclass(frozen=True)
class FollowTransition:
    next_state: FollowState
    scroll_to_end: bool = False


# [LAW:dataflow-not-control-flow] Primary state transition table.
_FOLLOW_TRANSITIONS: dict[tuple[FollowState, bool], FollowState] = {
    (FollowState.ACTIVE, True): FollowState.ACTIVE,
    (FollowState.ACTIVE, False): FollowState.ENGAGED,
    (FollowState.ENGAGED, True): FollowState.ACTIVE,
    (FollowState.ENGAGED, False): FollowState.ENGAGED,
    (FollowState.OFF, True): FollowState.OFF,
    (FollowState.OFF, False): FollowState.OFF,
}

_FOLLOW_TOGGLE: dict[FollowState, FollowState] = {
    FollowState.OFF: FollowState.ACTIVE,
    FollowState.ENGAGED: FollowState.OFF,
    FollowState.ACTIVE: FollowState.OFF,
}

_FOLLOW_SCROLL_BOTTOM: dict[FollowState, FollowState] = {
    FollowState.OFF: FollowState.OFF,
    FollowState.ENGAGED: FollowState.ACTIVE,
    FollowState.ACTIVE: FollowState.ACTIVE,
}

_FOLLOW_DEACTIVATE: dict[FollowState, FollowState] = {
    FollowState.OFF: FollowState.OFF,
    FollowState.ENGAGED: FollowState.ENGAGED,
    FollowState.ACTIVE: FollowState.ENGAGED,
}


# [LAW:dataflow-not-control-flow] One lookup controls transition and follow-scroll side effect.
_FOLLOW_EVENT_TRANSITIONS: dict[tuple[FollowState, FollowEvent, bool], FollowTransition] = {}

for _state in FollowState:
    for _at_bottom in (False, True):
        _FOLLOW_EVENT_TRANSITIONS[(_state, FollowEvent.USER_SCROLL, _at_bottom)] = (
            FollowTransition(next_state=_FOLLOW_TRANSITIONS[(_state, _at_bottom)], scroll_to_end=False)
        )
        _toggle_state = _FOLLOW_TOGGLE[_state]
        _FOLLOW_EVENT_TRANSITIONS[(_state, FollowEvent.TOGGLE, _at_bottom)] = (
            FollowTransition(
                next_state=_toggle_state,
                scroll_to_end=(_state == FollowState.OFF),
            )
        )
        _FOLLOW_EVENT_TRANSITIONS[(_state, FollowEvent.SCROLL_BOTTOM, _at_bottom)] = (
            FollowTransition(
                next_state=_FOLLOW_SCROLL_BOTTOM[_state],
                scroll_to_end=True,
            )
        )
        _FOLLOW_EVENT_TRANSITIONS[(_state, FollowEvent.DEACTIVATE, _at_bottom)] = (
            FollowTransition(
                next_state=_FOLLOW_DEACTIVATE[_state],
                scroll_to_end=False,
            )
        )


def transition_follow_state(
    current_state: FollowState,
    event: FollowEvent,
    *,
    at_bottom: bool,
) -> FollowTransition:
    """Return the deterministic follow transition for a follow event."""
    return _FOLLOW_EVENT_TRANSITIONS[(current_state, event, at_bottom)]


class FollowModeStore:
    """Reactive follow-mode state store.

    // [LAW:one-source-of-truth] Canonical follow state is `state` Observable.
    // [LAW:single-enforcer] `_apply_intent` is the sole transition application path.
    """

    def __init__(self, initial_state: FollowState):
        self.state: Observable[FollowState] = Observable(initial_state)
        self._intent_seq: int = 0
        self.intent: Observable[tuple[int, FollowEvent, bool]] = Observable(
            (0, FollowEvent.USER_SCROLL, True)
        )
        self.transition: Observable[tuple[int, FollowTransition]] = Observable(
            (0, FollowTransition(next_state=initial_state, scroll_to_end=False))
        )
        self._intent_reaction = reaction(
            lambda: self.intent.get(),
            self._apply_intent,
            fire_immediately=False,
        )

    def dispose(self) -> None:
        self._intent_reaction.dispose()

    def dispatch(self, event: FollowEvent, *, at_bottom: bool) -> None:
        self._intent_seq += 1
        self.intent.set((self._intent_seq, event, at_bottom))

    def _apply_intent(self, payload: tuple[int, FollowEvent, bool]) -> None:
        seq, event, at_bottom = payload
        current = self.state.get()
        next_transition = transition_follow_state(
            current,
            event,
            at_bottom=at_bottom,
        )
        self.state.set(next_transition.next_state)
        self.transition.set((seq, next_transition))
