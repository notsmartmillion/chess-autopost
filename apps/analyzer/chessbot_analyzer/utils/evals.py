"""Evaluation utilities: centipawn to bar value mapping, mate formatting."""

import math
from typing import Union, Optional


def cp_to_bar_value(cp: int, clamp: bool = True) -> float:
    """
    Convert centipawn evaluation to bar value (-1 to +1).
    
    Args:
        cp: Centipawn evaluation
        clamp: Whether to clamp to [-1, 1] range
        
    Returns:
        Bar value between -1 and 1
    """
    # Use tanh for smooth mapping
    bar_value = math.tanh(cp / 400.0)  # 400 cp ≈ 4 pawns for tanh(1)
    
    if clamp:
        return max(-1.0, min(1.0, bar_value))
    
    return bar_value


def format_evaluation(score: Union[int, dict], show_sign: bool = True) -> str:
    """
    Format evaluation for display.
    
    Args:
        score: Either centipawn int or dict with 'type' and 'value'
        show_sign: Whether to show + sign for positive values
        
    Returns:
        Formatted evaluation string
    """
    if isinstance(score, dict):
        if score.get("type") == "mate":
            mate_value = score.get("value", 0)
            if mate_value > 0:
                return f"#{mate_value}"
            else:
                return f"#-{abs(mate_value)}"
        else:
            cp = score.get("cp", 0)
    else:
        cp = score
    
    # Convert to pawns
    pawns = cp / 100.0
    
    if abs(pawns) < 0.1:
        return "0.0"
    
    if show_sign and pawns > 0:
        return f"+{pawns:.1f}"
    else:
        return f"{pawns:.1f}"


def is_winning_position(cp: int, threshold: int = 200) -> bool:
    """Check if position is winning based on centipawn threshold."""
    return cp > threshold


def is_losing_position(cp: int, threshold: int = -200) -> bool:
    """Check if position is losing based on centipawn threshold."""
    return cp < threshold


def get_eval_category(cp: int) -> str:
    """
    Categorize evaluation into human-readable terms.
    
    Args:
        cp: Centipawn evaluation
        
    Returns:
        Category string
    """
    if cp > 500:
        return "Winning"
    elif cp > 200:
        return "Advantage"
    elif cp > 50:
        return "Slight advantage"
    elif cp > -50:
        return "Equal"
    elif cp > -200:
        return "Slight disadvantage"
    elif cp > -500:
        return "Disadvantage"
    else:
        return "Losing"


def mate_in_n(cp: int) -> Optional[int]:
    """
    Extract mate-in-N from evaluation if it's a mate score.
    
    Args:
        cp: Centipawn evaluation (mate scores are typically very large)
        
    Returns:
        Mate-in-N or None if not a mate
    """
    # Mate scores are typically > 10000 or < -10000
    if cp > 10000:
        # Convert to mate-in-N (approximate)
        return max(1, (20000 - cp) // 100)
    elif cp < -10000:
        return max(1, (cp + 20000) // 100)
    
    return None
