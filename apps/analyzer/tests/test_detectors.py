import chess
from chessbot_analyzer.detectors import FeatureDetectors

def test_rook_file_pin():
    board = chess.Board("4k1r1/8/8/8/8/8/6B1/6K1 w - - 0 1")
    pins = FeatureDetectors.compute_pins(board)
    assert any(p.get("sq") == "g2" and p.get("attacker") == "g8" and p.get("king") == "g1" for p in pins)

def test_bishop_diag_pin():
    board = chess.Board("k7/8/8/8/8/4b3/5N2/6K1 w - - 0 1")
    pins = FeatureDetectors.compute_pins(board)
    assert any(p.get("sq") == "f2" and p.get("attacker") == "e3" and p.get("king") == "g1" for p in pins)
