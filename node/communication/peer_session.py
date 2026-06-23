import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from enum import Enum

from metrics.node_metrics import metrics, MetricField
from utils.exception_decorator import log_exceptions


class PeerState(Enum):
    PENDING = "pending"
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"


@dataclass
class PendingFragment:
    surb_id: bytes
    surb_key_tuple: tuple
    target_node: int
    payload: bytes
    is_cover: bool
    payload_hash: bytes
    round: int | None = None
    timestamp: datetime | None = None
    acked: bool = False
    pending_resend: bool = False


class PeerSession:
    def __init__(self, peer_id: int):
        self.peer_id = peer_id
        self.state: PeerState = PeerState.PENDING
        self._pending: dict[bytes, PendingFragment] = {}
        self._payload_to_surbs: dict[bytes, set] = {}
        self._retry_counts: dict[bytes, int] = {}
        self._last_surb_at: datetime | None = None

    @property
    def is_reachable(self) -> bool:
        return self.state == PeerState.REACHABLE

    @log_exceptions
    def track_outbound(
            self,
            surb_id: bytes,
            surb_key_tuple: tuple,
            payload: bytes,
            is_cover: bool,
            payload_hash: bytes | None = None,
            round: int | None = None,
    ) -> bytes:
        if payload_hash is None:
            payload_hash = hashlib.sha256(payload).digest()

        frag = PendingFragment(
            surb_id=surb_id,
            surb_key_tuple=surb_key_tuple,
            target_node=self.peer_id,
            payload=payload,
            is_cover=is_cover,
            payload_hash=payload_hash,
            round=round,
        )
        self._pending[surb_id] = frag

        if payload_hash not in self._payload_to_surbs:
            self._payload_to_surbs[payload_hash] = set()
        self._payload_to_surbs[payload_hash].add(surb_id)

        # only the first transmission of a logical message counts
        if not is_cover and len(self._payload_to_surbs[payload_hash]) == 1:
            metrics().increment(MetricField.UNACKED_MSG)

        return payload_hash

    @log_exceptions
    def mark_sent(self, surb_id: bytes) -> None:
        if surb_id in self._pending:
            self._pending[surb_id].timestamp = datetime.now(UTC)

    @log_exceptions
    def mark_acked(self, surb_id: bytes) -> float | None:
        # acks all fragments sharing the payload_hash; returns RTT in seconds on the first ack
        if surb_id not in self._pending:
            return None

        frag = self._pending[surb_id]
        payload_hash = frag.payload_hash
        already_acked = frag.acked

        # one logical message can be in flight under several SURBs; ack them all
        related_surb_ids = self._payload_to_surbs.get(payload_hash, {surb_id})
        for related_id in related_surb_ids:
            if related_id in self._pending:
                self._pending[related_id].acked = True

        if not already_acked and not frag.is_cover:
            metrics().decrement(MetricField.UNACKED_MSG)

        if already_acked or frag.timestamp is None:
            return None

        self._last_surb_at = datetime.now(UTC)
        return (self._last_surb_at - frag.timestamp).total_seconds()

    def record_surb_ack(self, surb_id: bytes) -> float | None:
        rtt = self.mark_acked(surb_id)
        self.state = PeerState.REACHABLE
        return rtt

    def record_resend_exhausted(self, payload_hash: bytes) -> None:
        # K-resend exhausted on an unacked fragment: no recent evidence of life.
        # flip state but keep _pending so a late SURB from the resend still in
        # flight (or its last-hop drop on a truly dead peer) is handled correctly.
        # MAX_RESENDS already caps the work; nothing else needs clearing.
        self.state = PeerState.UNREACHABLE

    def acked_since_last_send(self, payload_hash: bytes) -> bool:
        if self._last_surb_at is None:
            return False

        # timestamps of every send that carried this payload
        send_times = [
            self._pending[sid].timestamp
            for sid in self._payload_to_surbs.get(payload_hash, ())
            if sid in self._pending and self._pending[sid].timestamp is not None
        ]
        if not send_times:
            return False

        # true only if the most recent ack came after the latest send
        return self._last_surb_at >= max(send_times)

    def get_surb_key(self, surb_id: bytes) -> tuple | None:
        frag = self._pending.get(surb_id)
        return frag.surb_key_tuple if frag else None

    def has_surb(self, surb_id: bytes) -> bool:
        return surb_id in self._pending

    @log_exceptions
    def get_stale_fragments(self, older_than_seconds: float) -> list[PendingFragment]:
        self._clear_acked()

        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=older_than_seconds)
        stale = []

        for frag in list(self._pending.values()):
            if (
                    frag.timestamp
                    and frag.timestamp < cutoff
                    and not frag.acked
                    and not frag.pending_resend
                    and not frag.is_cover
            ):
                stale.append(frag)
                # acked stays False so mark_acked still fires UNACKED_MSG decrement on a delayed ack
                frag.pending_resend = True

        return stale

    def get_retry_count(self, payload_hash: bytes) -> int:
        return self._retry_counts.get(payload_hash, 0)

    def bump_retry_count(self, payload_hash: bytes) -> None:
        self._retry_counts[payload_hash] = self._retry_counts.get(payload_hash, 0) + 1

    def _clear_acked(self, cover_ttl_seconds: float = 30.0) -> int:
        now = datetime.now(UTC)
        cover_cutoff = now - timedelta(seconds=cover_ttl_seconds)

        # drop anything already acked, plus cover traffic old enough to expire
        to_delete = [
            sid
            for sid, frag in list(self._pending.items())
            if frag.acked or (frag.is_cover and frag.timestamp and frag.timestamp < cover_cutoff)
        ]

        for sid in to_delete:
            frag = self._pending[sid]
            if frag.payload_hash in self._payload_to_surbs:
                self._payload_to_surbs[frag.payload_hash].discard(sid)
                if not self._payload_to_surbs[frag.payload_hash]:
                    del self._payload_to_surbs[frag.payload_hash]
            del self._pending[sid]
        return len(to_delete)

    def all_acked(self) -> bool:
        return not any(not frag.acked and not frag.is_cover for frag in self._pending.values())


def find_surb_key(sessions: dict[int, PeerSession], surb_id: bytes) -> tuple | None:
    for session in sessions.values():
        key = session.get_surb_key(surb_id)
        if key is not None:
            return key
    return None


def find_session_by_surb(sessions: dict[int, PeerSession], surb_id: bytes) -> PeerSession | None:
    for session in sessions.values():
        if session.has_surb(surb_id):
            return session
    return None
