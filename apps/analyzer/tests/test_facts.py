# apps/analyzer/tests/test_facts.py
"""Tests for the Pass-1 fact extractor. No real Stockfish required."""

import json

import chess
import pytest

from chessbot_analyzer import facts as facts_mod
from chessbot_analyzer.facts import extract_facts, save_facts


# --------------------------------------------------------------------------- #
# Fake engines
# --------------------------------------------------------------------------- #


class FakeEngine:
    """Deterministic stand-in for StockfishEngine.

    Returns the first `multipv` legal moves (sorted for determinism) with a
    fixed set of cp scores, always from the POV of the side to move -- exactly
    like the real wrapper.
    """

    def __init__(self, cps=(50, -30, -60, -90)):
        self.cps = cps
        self.calls = []

    def analyse(self, board: chess.Board, multipv: int, depth: int):
        self.calls.append(board.fen())
        legal = sorted(board.legal_moves, key=lambda m: (m.from_square, m.to_square))
        legal = legal[: max(1, multipv)]
        infos = []
        for i, mv in enumerate(legal):
            tmp = board.copy()
            pv = [mv]
            tmp.push(mv)
            opp = sorted(tmp.legal_moves, key=lambda m: (m.from_square, m.to_square))
            if opp:
                pv.append(opp[0])
            infos.append(
                {
                    "pv": pv,
                    "cp": self.cps[i] if i < len(self.cps) else -200,
                    "mate": None,
                    "multipv": i + 1,
                }
            )
        return infos


class ConstEngine:
    """Engine that always reports a constant cp from the side-to-move POV."""

    def __init__(self, cp: int = 120):
        self.cp = cp

    def analyse(self, board: chess.Board, multipv: int, depth: int):
        legal = sorted(board.legal_moves, key=lambda m: (m.from_square, m.to_square))
        legal = legal[: max(1, multipv)]
        # White POV +cp -> from side-to-move POV that means +cp for White,
        # -cp for Black. This is what a real engine reports.
        stm_cp = self.cp if board.turn == chess.WHITE else -self.cp
        return [
            {"pv": [mv], "cp": stm_cp, "mate": None, "multipv": i + 1}
            for i, mv in enumerate(legal)
        ]


class BlunderEngine:
    """Engine that makes every played move look like a huge blunder.

    Best move from the position before the move is *never* the one played
    (it is the last legal move in sort order), and the eval after the move
    collapses for the mover.
    """

    def analyse(self, board: chess.Board, multipv: int, depth: int):
        legal = sorted(board.legal_moves, key=lambda m: (m.from_square, m.to_square))
        # Best = last legal move so the game's actual move is (almost) never best.
        ordered = list(reversed(legal))[: max(1, multipv)]
        # Side to move is always reported as much worse off than the previous
        # side was -> every move looks like it threw away ~600cp.
        stm_cp = 300 if board.turn == chess.WHITE else 300
        return [
            {"pv": [mv], "cp": stm_cp, "mate": None, "multipv": i + 1}
            for i, mv in enumerate(ordered)
        ]


PGN = """[Event "Test"]
[Site "Nowhere"]
[Date "2024.01.01"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]
[ECO "C60"]
[WhiteElo "2500"]
[BlackElo "2400"]
[TimeControl "600+5"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 1-0
"""


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #


def test_schema_keys_present():
    f = extract_facts(PGN, engine=FakeEngine(), depth=4, multipv=3, progress=False)

    assert set(["meta", "opening", "plies", "keyMoments", "summary"]) <= set(f)

    for key in (
        "white",
        "black",
        "date",
        "event",
        "site",
        "result",
        "eco",
        "whiteElo",
        "blackElo",
        "timeControl",
        "plyCount",
    ):
        assert key in f["meta"], key
    assert f["meta"]["white"] == "Alice"
    assert f["meta"]["plyCount"] == len(f["plies"]) == 8

    assert set(f["opening"]) == {"eco", "name"}
    assert f["opening"]["eco"] == "C60"  # falls back to the PGN header

    ply = f["plies"][0]
    for key in (
        "ply",
        "moveNumber",
        "side",
        "san",
        "uci",
        "from",
        "to",
        "pieceType",
        "fenBefore",
        "fenAfter",
        "isCapture",
        "capturedPiece",
        "isCheck",
        "isMate",
        "isStalemate",
        "isCastle",
        "promotion",
        "evalBeforeCp",
        "evalAfterCp",
        "mateBefore",
        "mateAfter",
        "cpLoss",
        "playedBest",
        "isSacrifice",
        "quality",
        "bestMoveSan",
        "bestMoveUci",
        "bestPvSan",
        "bestPvUci",
        "alternatives",
        "features",
        "threats",
    ):
        assert key in ply, key

    assert ply["ply"] == 1 and ply["moveNumber"] == 1 and ply["side"] == "white"
    assert ply["san"] == "e4" and ply["uci"] == "e2e4"
    assert ply["from"] == "e2" and ply["to"] == "e4"
    assert ply["pieceType"] == "pawn"

    for key in (
        "pins",
        "skewers",
        "hanging",
        "forks",
        "longRays",
        "batteries",
        "checkSquare",
        "pawnStructure",
        "material",
        "bishopPair",
        "kingSafety",
        "mobility",
        "phase",
        "centerControl",
    ):
        assert key in ply["features"], key

    for key in ("result", "plyCount", "decisive", "biggestSwingPly", "blunders",
                "brilliancies", "sacrifices"):
        assert key in f["summary"], key
    assert f["summary"]["decisive"] is True

    # Alternatives come from MultiPV 2..N of the position before the move.
    assert [a["rank"] for a in ply["alternatives"]] == [2, 3]


def test_output_is_json_serializable(tmp_path):
    f = extract_facts(PGN, engine=FakeEngine(), depth=4, multipv=2, progress=False)
    out = tmp_path / "nested" / "facts.json"
    save_facts(f, out)
    reloaded = json.loads(out.read_text(encoding="utf-8"))
    assert reloaded["meta"]["plyCount"] == f["meta"]["plyCount"]
    # json.dumps must not choke on chess objects anywhere in the tree
    json.dumps(f)


# --------------------------------------------------------------------------- #
# White-POV normalization
# --------------------------------------------------------------------------- #


def test_evals_are_white_pov_and_do_not_alternate():
    """A constant +1.2 for White must stay +120 on every ply, both colors."""
    f = extract_facts(PGN, engine=ConstEngine(cp=120), depth=4, multipv=1, progress=False)

    befores = [p["evalBeforeCp"] for p in f["plies"]]
    afters = [p["evalAfterCp"] for p in f["plies"]]
    assert befores == [120] * len(befores), befores
    assert afters == [120] * len(afters), afters

    # Explicitly: no sign alternation by side to move.
    white_evals = [p["evalBeforeCp"] for p in f["plies"] if p["side"] == "white"]
    black_evals = [p["evalBeforeCp"] for p in f["plies"] if p["side"] == "black"]
    assert all(e > 0 for e in white_evals)
    assert all(e > 0 for e in black_evals)


def test_eval_after_matches_next_eval_before():
    """The single-analysis contract: eval after ply N == eval before ply N+1."""
    engine = FakeEngine()
    f = extract_facts(PGN, engine=engine, depth=4, multipv=2, progress=False)
    plies = f["plies"]
    for a, b in zip(plies, plies[1:]):
        assert a["evalAfterCp"] == b["evalBeforeCp"]

    # And each position is analysed exactly once: 8 plies -> 8 pre-positions
    # + 1 final position = 9 engine calls.
    assert len(engine.calls) == len(plies) + 1
    assert len(set(engine.calls)) == len(engine.calls)


# --------------------------------------------------------------------------- #
# Feature detectors
# --------------------------------------------------------------------------- #


def test_pin_detected():
    """Black knight on f6 pinned to the king on d8 by the bishop on g5."""
    board = chess.Board("rnbk1b1r/pppp1ppp/5n2/4p1B1/8/8/PPPPPPPP/RN1QKBNR b KQ - 0 1")
    pins = facts_mod._detect_pins(board)
    match = [p for p in pins if p["pinned"] == "f6"]
    assert match, pins
    p = match[0]
    assert p["attacker"] == "g5"
    assert p["king"] == "d8"
    assert p["color"] == "black"
    assert p["pinnedPiece"] == "knight"
    assert p["attackerPiece"] == "bishop"
    assert "e7" in p["ray"] and "d8" in p["ray"]


def test_long_ray_fianchetto_bishop_hits_d4():
    """The g7 bishop shoots down the long diagonal and runs into a pawn on d4."""
    board = chess.Board("6k1/6b1/8/8/3P4/8/8/6K1 w - - 0 1")
    rays = facts_mod._detect_long_rays(board)
    diag = [
        r
        for r in rays
        if r["from"] == "g7" and r["piece"] == "bishop" and "d4" in r["ray"]
    ]
    assert diag, rays
    entry = diag[0]
    assert entry["color"] == "black"
    assert entry["length"] >= 3
    assert entry["open"] is True
    assert [h["square"] for h in entry["hits"]] == ["d4"]
    assert entry["hits"][0]["piece"] == "pawn"
    assert entry["hits"][0]["color"] == "white"
    # Short rays are filtered out.
    assert all(r["length"] >= 3 for r in rays)


def test_isolated_and_doubled_pawns():
    """White a-pawns are doubled and isolated; e4 is isolated too."""
    board = chess.Board("6k1/8/8/8/P3P3/P7/8/6K1 w - - 0 1")
    ps = facts_mod._pawn_structure(board)
    assert sorted(ps["isolated"]["white"]) == ["a3", "a4", "e4"]
    assert sorted(ps["doubled"]["white"]) == ["a3", "a4"]
    assert ps["isolated"]["black"] == []
    # No black pawns anywhere -> every white pawn is passed.
    assert sorted(ps["passed"]["white"]) == ["a3", "a4", "e4"]


def test_fork_and_hanging_detection():
    """Knight on c7 forks the king on e8 and the rook on a8."""
    board = chess.Board("r3k3/2N5/8/8/8/8/8/6K1 b - - 0 1")
    forks = facts_mod._detect_forks(board)
    knight = [f for f in forks if f["square"] == "c7"]
    assert knight, forks
    targets = {t["square"] for t in knight[0]["targets"]}
    assert {"a8", "e8"} <= targets
    assert knight[0]["color"] == "white"


def test_hanging_detection():
    """The undefended black knight on d5 is attacked by the rook on d1."""
    board = chess.Board("4k3/8/8/3n4/8/8/8/3RK3 w - - 0 1")
    hanging = facts_mod._detect_hanging(board)
    match = [h for h in hanging if h["square"] == "d5"]
    assert match, hanging
    h = match[0]
    assert h["piece"] == "knight"
    assert h["color"] == "black"
    assert h["attackers"] == ["d1"]
    assert h["defenders"] == []
    assert h["value"] == 320
    # The rook is defended by its king and attacked by nobody -> safe.
    assert not any(x["square"] == "d1" for x in hanging)


def test_features_present_on_a_real_walk():
    f = extract_facts(PGN, engine=FakeEngine(), depth=4, multipv=2, progress=False)
    last = f["plies"][-1]["features"]
    assert last["phase"] in ("opening", "middlegame", "endgame")
    assert last["mobility"]["white"] > 0 and last["mobility"]["black"] > 0
    assert last["material"]["white"]["pawn"] == 8
    assert last["material"]["balancePawns"] == 0.0
    assert isinstance(last["centerControl"]["white"], int)
    assert last["checkSquare"] is None
    # Rooks/bishops on the initial-ish position still give some long rays.
    assert isinstance(last["longRays"], list)


# --------------------------------------------------------------------------- #
# Quality classification
# --------------------------------------------------------------------------- #


def test_blunder_classification_with_big_cp_loss():
    f = extract_facts(PGN, engine=BlunderEngine(), depth=4, multipv=2, progress=False)
    plies = f["plies"]
    # Every ply loses ~600cp from the mover's POV.
    losses = [p["cpLoss"] for p in plies if not p["playedBest"]]
    assert losses and all(l >= 300 for l in losses), losses
    blunders = [p for p in plies if p["quality"] == "blunder"]
    assert blunders, [p["quality"] for p in plies]
    # Book classification must not swallow real blunders inside the first 10 plies.
    assert blunders[0]["ply"] <= 10
    assert f["summary"]["blunders"] == [p["ply"] for p in blunders]
    kinds = {m["kind"] for m in f["keyMoments"]}
    assert "blunder" in kinds
    # keyMoments sorted by score desc
    scores = [m["score"] for m in f["keyMoments"]]
    assert scores == sorted(scores, reverse=True)


def test_quality_helper_thresholds():
    base = dict(ply=20, in_book=False, played_best=False, only_move=False, is_sacrifice=False)
    assert facts_mod._classify_quality(cp_loss=400, **base) == "blunder"
    assert facts_mod._classify_quality(cp_loss=200, **base) == "mistake"
    assert facts_mod._classify_quality(cp_loss=80, **base) == "inaccuracy"
    assert facts_mod._classify_quality(cp_loss=10, **base) == "good"

    book = dict(base, ply=4, in_book=True)
    assert facts_mod._classify_quality(cp_loss=0, **book) == "book"

    only = dict(base, played_best=True, only_move=True)
    assert facts_mod._classify_quality(cp_loss=0, **only) == "best"
    only_sac = dict(only, is_sacrifice=True)
    assert facts_mod._classify_quality(cp_loss=0, **only_sac) == "brilliant"


def test_book_moves_at_start():
    """With a flat eval nothing is lost, so the first 10 plies read as book."""
    f = extract_facts(PGN, engine=ConstEngine(cp=20), depth=4, multipv=1, progress=False)
    qualities = [p["quality"] for p in f["plies"]]
    assert all(q == "book" for q in qualities), qualities
    assert all(p["cpLoss"] == 0 for p in f["plies"])


# --------------------------------------------------------------------------- #
# Terminal positions / misc
# --------------------------------------------------------------------------- #


def test_checkmate_is_flagged_and_final_position_not_analysed():
    engine = FakeEngine()
    fools = '[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1\n'
    f = extract_facts(fools, engine=engine, depth=4, multipv=2, progress=False)
    last = f["plies"][-1]
    assert last["san"] == "Qh4#"
    assert last["isMate"] is True
    assert last["isCheck"] is True
    assert last["mateAfter"] == 0
    # 4 plies -> 4 pre-move analyses, no analysis of the mated position.
    assert len(engine.calls) == 4
    assert f["summary"]["decisive"] is True
    assert any(m["kind"] == "checkmate" for m in f["keyMoments"])


def test_max_plies_and_castling_flags():
    pgn = '[Result "*"]\n\n1. e4 e5 2. Nf3 Nf6 3. Bc4 Bc5 4. O-O O-O *\n'
    f = extract_facts(pgn, engine=FakeEngine(), depth=4, multipv=2, max_plies=4, progress=False)
    assert len(f["plies"]) == 4

    full = extract_facts(pgn, engine=FakeEngine(), depth=4, multipv=2, progress=False)
    castles = [p for p in full["plies"] if p["isCastle"]]
    assert [c["isCastle"] for c in castles] == ["kingside", "kingside"]
    assert full["plies"][-1]["features"]["kingSafety"]["white"]["castled"] is True
    assert full["plies"][-1]["features"]["kingSafety"]["black"]["castled"] is True


def test_capture_and_promotion_fields():
    pgn = '[Result "*"]\n\n1. e4 d5 2. exd5 Qxd5 *\n'
    f = extract_facts(pgn, engine=FakeEngine(), depth=4, multipv=2, progress=False)
    exd5 = f["plies"][2]
    assert exd5["san"] == "exd5"
    assert exd5["isCapture"] is True
    assert exd5["capturedPiece"] == "pawn"
    assert f["plies"][0]["capturedPiece"] is None


def test_detector_failure_does_not_kill_the_run(monkeypatch):
    monkeypatch.setattr(
        facts_mod, "_detect_forks", lambda board: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    f = extract_facts(PGN, engine=FakeEngine(), depth=4, multipv=2, progress=False)
    assert len(f["plies"]) == 8
    assert f["plies"][0]["features"]["forks"] == []


def test_opening_name_from_optional_eco_table(tmp_path, monkeypatch):
    """A local data/eco.tsv (when present) supplies the opening name + book plies."""
    table = tmp_path / "eco.tsv"
    table.write_text(
        "# eco\tname\tpgn_moves\n"
        "C60\tRuy Lopez\t1. e4 e5 2. Nf3 Nc6 3. Bb5\n"
        "C20\tKing's Pawn Game\t1. e4 e5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(facts_mod, "_eco_path", lambda: table)
    facts_mod._load_eco_table.cache_clear()
    try:
        f = extract_facts(PGN, engine=FakeEngine(), depth=4, multipv=2, progress=False)
        assert f["opening"] == {"eco": "C60", "name": "Ruy Lopez"}
        assert f["summary"]["bookPlies"] == 5
        assert [p["quality"] for p in f["plies"][:5]] == ["book"] * 5
    finally:
        facts_mod._load_eco_table.cache_clear()


def test_missing_eco_table_is_tolerated(tmp_path, monkeypatch):
    monkeypatch.setattr(facts_mod, "_eco_path", lambda: tmp_path / "nope.tsv")
    facts_mod._load_eco_table.cache_clear()
    try:
        assert facts_mod._load_eco_table() == ()
        assert facts_mod._match_opening(["e4", "e5"]) == (None, None, 0)
    finally:
        facts_mod._load_eco_table.cache_clear()


def test_progress_writes_to_stderr(capsys):
    extract_facts(PGN, engine=FakeEngine(), depth=4, multipv=1, progress=True)
    err = capsys.readouterr().err
    assert "[facts] analysed ply" in err


def test_empty_pgn_raises():
    with pytest.raises(ValueError):
        extract_facts("", engine=FakeEngine(), progress=False)
