"""A spoken impossibility about a capture is a legality claim — checkable.

Shipped live in Anand-Gelfand: "the d7 pawn is pinned against its own king,
so it can't do the recapturing" — over a position where dxc6 was legal. A pin
forbids leaving the line between piece and king; capturing the pinning piece
removes the attacker and is almost always legal.
"""

import sys
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services" / "orchestrator"))

from chessbot_analyzer.facts import _detect_pins  # noqa: E402
import verify_render  # noqa: E402


def rossolimo_after_bxc6() -> chess.Board:
    board = chess.Board()
    for san in ["e4", "c5", "Nf3", "Nc6", "Bb5", "e6", "Bxc6"]:
        board.push_san(san)
    return board


def test_pin_fact_knows_the_pinner_can_be_captured():
    pins = _detect_pins(rossolimo_after_bxc6())
    d7 = [p for p in pins if p["pinned"] == "d7"]
    assert d7, f"expected a d7 pin, got {pins}"
    assert d7[0]["canCaptureAttacker"] is True
    assert d7[0]["attacker"] == "c6"


def test_pin_fact_knows_when_the_pinner_is_out_of_reach():
    # A knight pinned on the e-file by a rook: it cannot leave the file AND
    # cannot capture the far-away pinner — the one case "frozen" is true.
    board = chess.Board("4k3/8/4n3/8/8/8/8/4R2K b - - 0 1")
    pins = _detect_pins(board)
    e6 = [p for p in pins if p["pinned"] == "e6"]
    assert e6, f"expected an e6 pin, got {pins}"
    assert e6[0]["canCaptureAttacker"] is False


def _run_claims_check(text: str, board: chess.Board, move_san: str):
    prev = board.copy()
    move = prev.pop()  # board arrives AFTER the move; recover from/to
    frm, to = chess.square_name(move.from_square), chess.square_name(move.to_square)
    script = {
        "beats": [{
            "id": "b0001", "kind": "move", "text": text, "ply": 7,
            "fen": board.fen(), "move": {"from": frm, "to": to, "san": move_san},
        }],
    }
    rep = verify_render.Report()
    verify_render.check_narration(script, {"plies": []}, rep)
    return [m for lvl, sec, m in rep.rows if lvl == "ERROR" and sec == "claims"]


def test_the_published_sentence_is_caught():
    board = rossolimo_after_bxc6()
    errors = _run_claims_check(
        "bishop takes c6, giving away the bishop pair. And notice, the d7 "
        "pawn is pinned against its own king, so it can't do the recapturing.",
        board, "Bxc6",
    )
    assert errors and "dxc6" in errors[0]


def test_a_true_impossibility_is_left_alone():
    # 1.e4 e5 2.Nf3 Nc6 3.d4: after ...exd4 White recaptures — but claim is
    # about a capture on d4 by a bishop, and no black bishop can take there.
    board = chess.Board()
    for san in ["e4", "e5", "Nf3", "Nc6", "d4"]:
        board.push_san(san)
    errors = _run_claims_check(
        "The bishop can't capture on d4 — it has never moved.",
        board, "d4",
    )
    assert errors == []


def test_plain_narration_is_untouched():
    board = rossolimo_after_bxc6()
    errors = _run_claims_check(
        "Bishop takes c6, and Black will simply recapture with the b-pawn.",
        board, "Bxc6",
    )
    assert errors == []


def test_en_passant_is_a_named_fact():
    """The model wrote "pawn takes g6 in passing" because nothing told it the
    move was en passant; now the fact sheet names it."""
    from tests.test_facts import FakeEngine  # deterministic, no Stockfish
    from chessbot_analyzer.facts import extract_facts

    # Shortest legal en passant: 1.e4 Nf6 2.e5 d5 3.exd6
    pgn = '[White "A"]\n[Black "B"]\n[Result "*"]\n\n1. e4 Nf6 2. e5 d5 3. exd6 *'
    facts = extract_facts(pgn, engine=FakeEngine(), depth=4, multipv=1,
                          progress=False)
    plies = {p["ply"]: p for p in facts["plies"]}
    assert plies[5]["isEnPassant"] is True
    assert plies[5]["san"] == "exd6"
    assert all(not p["isEnPassant"] for n, p in plies.items() if n != 5)


def test_spoken_forms_change_only_the_voice():
    """Respellings go to the synthesis service; written text stays written."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]
                          / "services" / "orchestrator"))
    import tts

    spoken = tts._spoken_form("The capture comes sideways, en passant.")
    assert "on passont" in spoken and "en passant" not in spoken
    # Names are case-sensitive: prose survives, surnames are pinned.
    assert tts._spoken_form("a geller of a move") == "a geller of a move"
    assert tts._spoken_form("Geller played on.") == "Gheller played on."
    assert tts._spoken_form("Anand and Gelfand") == "Ahnand and Ghelfand"


def test_cannot_take_everything_is_commentary_not_a_claim():
    """Four pieces hang at once; "cannot possibly take everything" is true.

    The gate held a correct video because this sentence matched the
    impossibility pattern and the checker tested one specific capture.
    """
    board = rossolimo_after_bxc6()
    errors = _run_claims_check(
        "Another loose pawn, thrown forward. Black cannot possibly take "
        "everything.",
        board, "Bxc6",
    )
    assert errors == []
    # And quantifiers must not blind it to the real thing.
    errors = _run_claims_check(
        "The d7 pawn is pinned, so it cannot take the bishop.",
        board, "Bxc6",
    )
    assert errors != []


def test_king_has_to_move_is_not_read_as_a_rook_claim():
    """The subject of "has to move" is the nearest piece, not any piece.

    "uncovers the rook on e2 — check down the file, and Black's king has to
    move" flagged a published video: the pattern matched the ROOK across the
    sentence, found it safe where it stood, and called true narration a lie
    (the engine said onlyKingMoves). Verified here through check_narration
    with the real facts shape.
    """
    script = {
        "beats": [{
            "id": "b0073", "kind": "move", "ply": 71,
            "fen": chess.Board().fen(),  # any legal position; ev decides
            "move": {"from": "e3", "to": "d4", "san": "Kd4+"},
            "text": ("King to d4 uncovers the rook on e2 — check down the "
                     "file, and Black's king has to move."),
        }],
    }
    facts = {"plies": [{
        "ply": 71,
        "features": {"checkEvasions": {
            "kingMoves": ["Kf7", "Kd7", "Kd6", "Kf5"], "blocks": [],
            "captures": [], "canBlock": False, "canCapture": False,
            "onlyKingMoves": True, "isDouble": False, "isMate": False,
        }},
    }]}
    rep = verify_render.Report()
    verify_render.check_narration(script, facts, rep)
    factual = [m for lvl, sec, m in rep.rows
               if lvl == "ERROR" and sec == "claims"]
    assert factual == [], factual


def test_engine_contradictions_block_uploads():
    """The engine-contradiction check must live in a blocking section."""
    src = (Path(__file__).resolve().parents[3] / "services" / "orchestrator"
           / "verify_render.py").read_text(encoding="utf-8")
    assert 'rep.error("narration", f"claim contradicts' not in src
    assert 'rep.error("claims", f"claim contradicts' in src


def test_a_contrastive_clause_flips_the_meaning():
    """"cannot wander — but capturing is different" AFFIRMS the capture.

    Held a correct Korchnoi-Carlsen render whose narration was demonstrating
    the pin rule exactly as taught: a pinned piece cannot move away, but may
    take the pinner, because that removes the attacker.
    """
    board = rossolimo_after_bxc6()
    errors = _run_claims_check(
        "The d7 pawn is tied to its king, so it cannot wander — but "
        "capturing the bishop is a different matter, because that removes "
        "the attacker altogether.",
        board, "Bxc6",
    )
    assert errors == [], errors


def test_the_real_falsehood_still_fails_without_a_contrast():
    board = rossolimo_after_bxc6()
    errors = _run_claims_check(
        "The d7 pawn is pinned and so it cannot recapture.", board, "Bxc6")
    assert errors != []
