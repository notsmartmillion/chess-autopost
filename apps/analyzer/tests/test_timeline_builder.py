# apps/analyzer/tests/test_timeline_builder.py

import chess

from chessbot_analyzer.timeline import TimelineBuilder


class FakeEngine:
    """
    Very lightweight fake engine for tests.
    - Returns first 3 legal moves as MultiPV lines with dummy cp scores.
    """

    def analyse(self, board: chess.Board, multipv: int, depth: int):
        legal = list(board.legal_moves)
        # ensure deterministic order
        legal = sorted(legal, key=lambda m: (m.from_square, m.to_square))[: max(1, multipv)]
        infos = []
        base_cp = 0
        for i, mv in enumerate(legal, start=1):
            # Build a tiny PV: single move (or two plies if available)
            tmp = board.copy()
            pv = [mv]
            tmp.push(mv)
            # If opponent has any legal move, add one to make it 2 plies
            opp_legal = list(tmp.legal_moves)
            if opp_legal:
                pv.append(opp_legal[0])

            infos.append({"pv": pv, "cp": base_cp + (50 if i == 1 else -30 * i), "mate": None})
        return infos


def test_timeline_from_pgn_with_alts_and_pins():
    pgn = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 *"
    builder = TimelineBuilder(engine=FakeEngine())

    tl = builder.from_pgn(pgn, alt_preview_plies=2, alt_max=2)
    assert tl.scenes, "No scenes produced"
    # There should be main scenes for each ply and alt + reset scenes
    types = [s["type"] for s in tl.scenes]
    assert "main" in types and "alt" in types and "reset" in types

    # Main scenes should include pins/attacked and lastMoveArrow
    main = [s for s in tl.scenes if s["type"] == "main"][0]
    assert "pins" in main and "attacked" in main and "lastMoveArrow" in main
    assert isinstance(main["pins"], list)
    # Pin entries include 'color'
    for p in main["pins"]:
        assert "color" in p

    # Alt scene should have pv + arrows and attacked after final step
    alt = [s for s in tl.scenes if s["type"] == "alt"][0]
    assert isinstance(alt["pv"], list) and len(alt["pv"]) >= 1
    assert isinstance(alt["arrows"], list) and len(alt["arrows"]) >= 1
    assert "attacked" in alt and "durationMs" in alt

    # Duration clamping works
    assert 1000 < alt["durationMs"] <= 2500

    # Total duration accumulates
    assert tl.totalDurationMs > 0
