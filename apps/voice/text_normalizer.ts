/**
 * Text normalization for TTS to ensure natural pronunciation.
 */

/**
 * Normalize text for TTS synthesis
 */
export function normalizeText(text: string): string {
  let normalized = text;
  
  // Remove or replace chess notation artifacts
  normalized = normalized.replace(/[+#!?]/g, ''); // Remove check, mate, good, bad move symbols
  
  // Normalize square names for pronunciation
  normalized = normalized.replace(/\b([a-h])([1-8])\b/g, (match, file, rank) => {
    const fileNames: Record<string, string> = {
      'a': 'ay', 'b': 'bee', 'c': 'see', 'd': 'dee',
      'e': 'ee', 'f': 'eff', 'g': 'gee', 'h': 'aitch'
    };
    return `${fileNames[file] || file} ${rank}`;
  });
  
  // Normalize piece names
  normalized = normalized.replace(/\bK\b/g, 'King');
  normalized = normalized.replace(/\bQ\b/g, 'Queen');
  normalized = normalized.replace(/\bR\b/g, 'Rook');
  normalized = normalized.replace(/\bB\b/g, 'Bishop');
  normalized = normalized.replace(/\bN\b/g, 'Knight');
  normalized = normalized.replace(/\bP\b/g, 'Pawn');
  
  // Normalize move notation
  normalized = normalized.replace(/\bO-O-O\b/g, 'castles queenside');
  normalized = normalized.replace(/\bO-O\b/g, 'castles kingside');
  
  // Normalize captures
  normalized = normalized.replace(/x/g, 'takes');
  
  // Normalize check and mate
  normalized = normalized.replace(/\bcheck\b/gi, 'check');
  normalized = normalized.replace(/\bmate\b/gi, 'mate');
  
  // Normalize evaluation symbols
  normalized = normalized.replace(/\+(\d+\.?\d*)/g, 'plus $1');
  normalized = normalized.replace(/-(\d+\.?\d*)/g, 'minus $1');
  normalized = normalized.replace(/#(\d+)/g, 'mate in $1');
  
  // Normalize common chess terms
  normalized = normalized.replace(/\bpin\b/gi, 'pin');
  normalized = normalized.replace(/\bfork\b/gi, 'fork');
  normalized = normalized.replace(/\bskewer\b/gi, 'skewer');
  normalized = normalized.replace(/\bdiscovered\b/gi, 'discovered');
  normalized = normalized.replace(/\bdouble\b/gi, 'double');
  normalized = normalized.replace(/\btriple\b/gi, 'triple');
  
  // Normalize opening names
  normalized = normalized.replace(/\bSicilian\b/gi, 'Sicilian');
  normalized = normalized.replace(/\bFrench\b/gi, 'French');
  normalized = normalized.replace(/\bCaro-Kann\b/gi, 'Caro Kann');
  normalized = normalized.replace(/\bRuy Lopez\b/gi, 'Ruy Lopez');
  normalized = normalized.replace(/\bItalian\b/gi, 'Italian');
  normalized = normalized.replace(/\bEnglish\b/gi, 'English');
  
  // Clean up extra spaces and punctuation
  normalized = normalized.replace(/\s+/g, ' ');
  normalized = normalized.replace(/\s+([,.!?])/g, '$1');
  normalized = normalized.trim();
  
  return normalized;
}

/**
 * Normalize evaluation for speech
 */
export function normalizeEvaluation(eval: string): string {
  let normalized = eval;
  
  // Handle mate scores
  normalized = normalized.replace(/#(\d+)/g, 'mate in $1');
  normalized = normalized.replace(/#-(\d+)/g, 'mate in $1 for black');
  
  // Handle centipawn scores
  normalized = normalized.replace(/\+(\d+\.?\d*)/g, (match, value) => {
    const num = parseFloat(value);
    if (num >= 1) {
      return `plus ${num.toFixed(1)} pawns`;
    } else {
      return `plus ${(num * 100).toFixed(0)} centipawns`;
    }
  });
  
  normalized = normalized.replace(/-(\d+\.?\d*)/g, (match, value) => {
    const num = parseFloat(value);
    if (num >= 1) {
      return `minus ${num.toFixed(1)} pawns`;
    } else {
      return `minus ${(num * 100).toFixed(0)} centipawns`;
    }
  });
  
  return normalized;
}

/**
 * Normalize move for speech
 */
export function normalizeMove(move: string): string {
  let normalized = move;
  
  // Handle castling
  normalized = normalized.replace(/O-O-O/g, 'castles queenside');
  normalized = normalized.replace(/O-O/g, 'castles kingside');
  
  // Handle piece moves
  normalized = normalized.replace(/^([KQRBN])([a-h])([1-8])/g, (match, piece, file, rank) => {
    const pieceNames: Record<string, string> = {
      'K': 'King', 'Q': 'Queen', 'R': 'Rook', 'B': 'Bishop', 'N': 'Knight'
    };
    const fileNames: Record<string, string> = {
      'a': 'ay', 'b': 'bee', 'c': 'see', 'd': 'dee',
      'e': 'ee', 'f': 'eff', 'g': 'gee', 'h': 'aitch'
    };
    return `${pieceNames[piece]} to ${fileNames[file]} ${rank}`;
  });
  
  // Handle pawn moves
  normalized = normalized.replace(/^([a-h])([1-8])/g, (match, file, rank) => {
    const fileNames: Record<string, string> = {
      'a': 'ay', 'b': 'bee', 'c': 'see', 'd': 'dee',
      'e': 'ee', 'f': 'eff', 'g': 'gee', 'h': 'aitch'
    };
    return `Pawn to ${fileNames[file]} ${rank}`;
  });
  
  // Handle captures
  normalized = normalized.replace(/x/g, 'takes');
  
  // Handle check and mate
  normalized = normalized.replace(/\+/g, 'check');
  normalized = normalized.replace(/#/g, 'mate');
  
  return normalized;
}

/**
 * Add natural pauses and emphasis
 */
export function addSpeechEnhancements(text: string): string {
  let enhanced = text;
  
  // Add pauses after important moves
  enhanced = enhanced.replace(/(\w+ takes \w+)/g, '$1...');
  enhanced = enhanced.replace(/(mate in \d+)/g, '$1!');
  enhanced = enhanced.replace(/(check)/g, '$1!');
  
  // Add emphasis for key terms
  enhanced = enhanced.replace(/\b(brilliant|excellent|blunder|mistake)\b/g, '<emphasis level="strong">$1</emphasis>');
  
  return enhanced;
}
