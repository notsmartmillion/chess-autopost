export type Sq = string; // "e4"

export interface Pin {
  sq: Sq;
  ray: Sq[];
  attacker?: Sq;
  king?: Sq;
  color: "white" | "black";
}

export interface Attacked {
  white: Sq[];
  black: Sq[];
}

export interface SceneMain {
  type: "main";
  id: string;              // e.g., "m23"
  fen: string;
  move: string;            // SAN
  lastMoveArrow: [Sq, Sq];
  evalBarTarget: number;   // -1..+1, White POV (positive = White better)
  pins: Pin[];
  attacked: Attacked;
  durationMs: number;
  moveNumber?: number;
  player?: "white" | "black";
  captured?: boolean;
  tag?: string | null;     // book | best | great | inaccuracy | mistake | blunder
  cueTimes?: Record<string, number>; // fraction of scene duration, 0..1
}

export interface SceneAlt {
  type: "alt";
  id: string;
  label: string;           // "Alternative"
  fen: string;             // branch-point FEN (position before the played move)
  pv: string[];            // SAN sequence
  arrows: [Sq, Sq][];
  attacked: Attacked;
  cp?: number | null;
  mate?: number | null;
  durationMs: number;
  multipv: number;
  cueTimes?: Record<string, number>; // fraction of scene duration, 0..1
}

export interface SceneReset {
  type: "reset";
  id: string;
  durationMs: number;
}

export type Scene = SceneMain | SceneAlt | SceneReset;

export interface Timeline {
  meta: {
    white?: string | null;
    black?: string | null;
    date?: string | null;
    event?: string | null;
    result?: string | null;
    eco?: string | null;
    introMs?: number;
    outroMs?: number;
  };
  scenes: Scene[];
  totalDurationMs: number;
}

export interface VoiceLine {
  id: string;
  text: string;
  durationMs?: number;
}
