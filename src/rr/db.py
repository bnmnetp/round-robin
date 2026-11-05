"""SQLite storage. Standings are always computed from match scores, never stored,
so correcting a score fixes everything that depends on it."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Column,
    ForeignKey,
    String,
    Table,
    create_engine,
    event,
    func,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)


class Base(DeclarativeBase):
    pass


class Player(Base):
    __tablename__ = "player"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    active: Mapped[bool] = mapped_column(default=True)


tournament_player = Table(
    "tournament_player",
    Base.metadata,
    Column(
        "tournament_id",
        ForeignKey("tournament.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("player_id", ForeignKey("player.id"), primary_key=True),
)

sit_out = Table(
    "sit_out",
    Base.metadata,
    Column("round_id", ForeignKey("round.id", ondelete="CASCADE"), primary_key=True),
    Column("player_id", ForeignKey("player.id"), primary_key=True),
)

SETUP = "setup"  # schedule generated, can still be reshuffled
STARTED = "started"


class Tournament(Base):
    __tablename__ = "tournament"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(32), unique=True)  # public URL
    name: Mapped[str] = mapped_column(String(100))
    date: Mapped[dt.date]
    num_courts: Mapped[int]
    num_rounds: Mapped[int]
    seed: Mapped[int]
    ranking: Mapped[str] = mapped_column(String(10))  # standings.TOTAL / AVERAGE
    status: Mapped[str] = mapped_column(String(10), default=SETUP)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

    players: Mapped[list[Player]] = relationship(
        secondary=tournament_player, order_by=lambda: func.lower(Player.name)
    )
    rounds: Mapped[list[Round]] = relationship(
        back_populates="tournament",
        order_by=lambda: Round.number,
        cascade="all, delete-orphan",
    )

    def matches(self) -> list[Match]:
        return [m for r in self.rounds for m in r.matches]

    @property
    def current_round(self) -> Round | None:
        """The first round that still has a game to report."""
        return next((r for r in self.rounds if not r.complete), None)

    @property
    def rounds_complete(self) -> int:
        return sum(1 for r in self.rounds if r.complete)

    @property
    def finished(self) -> bool:
        return self.status == STARTED and self.current_round is None


class Round(Base):
    __tablename__ = "round"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.id", ondelete="CASCADE")
    )
    number: Mapped[int]  # 1-based

    tournament: Mapped[Tournament] = relationship(back_populates="rounds")
    matches: Mapped[list[Match]] = relationship(
        back_populates="round",
        order_by=lambda: Match.court,
        cascade="all, delete-orphan",
    )
    sitting_out: Mapped[list[Player]] = relationship(
        secondary=sit_out, order_by=lambda: func.lower(Player.name)
    )

    @property
    def complete(self) -> bool:
        return all(m.scored for m in self.matches)

    @property
    def reported(self) -> int:
        return sum(1 for m in self.matches if m.scored)


class Match(Base):
    __tablename__ = "match"

    id: Mapped[int] = mapped_column(primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("round.id", ondelete="CASCADE"))
    court: Mapped[int]  # 1-based
    a1_id: Mapped[int] = mapped_column(ForeignKey("player.id"))
    a2_id: Mapped[int] = mapped_column(ForeignKey("player.id"))
    b1_id: Mapped[int] = mapped_column(ForeignKey("player.id"))
    b2_id: Mapped[int] = mapped_column(ForeignKey("player.id"))
    score_a: Mapped[int | None]
    score_b: Mapped[int | None]

    round: Mapped[Round] = relationship(back_populates="matches")
    a1: Mapped[Player] = relationship(foreign_keys=[a1_id])
    a2: Mapped[Player] = relationship(foreign_keys=[a2_id])
    b1: Mapped[Player] = relationship(foreign_keys=[b1_id])
    b2: Mapped[Player] = relationship(foreign_keys=[b2_id])

    @property
    def scored(self) -> bool:
        return self.score_a is not None and self.score_b is not None

    @property
    def team_a(self) -> tuple[Player, Player]:
        return (self.a1, self.a2)

    @property
    def team_b(self) -> tuple[Player, Player]:
        return (self.b1, self.b2)


def make_engine(url: str) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(conn, _record):
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def init_db(url: str) -> sessionmaker:
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
