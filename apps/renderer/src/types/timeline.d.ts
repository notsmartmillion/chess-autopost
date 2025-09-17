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
  move: string;            // UCI or SAN
  lastMoveArrow: [Sq, Sq];
  evalBarTarget: number;   // -1..+1 (clamped)
  pins: Pin[];
  attacked: Attacked;
  durationMs: number;
  moveNumber?: number;
  player?: "white" | "black";
  cueTimes?: Record<string, number>; // e.g., { "pinned": 1.17, "best": 0.62 }
}

export interface SceneAlt {
  type: "alt";
  id: string;
  label: string;           // "Alt #1"
  pv: string[];            // SAN sequence
  arrows: [Sq, Sq][];
  attacked: Attacked;
  cp?: number; 
  mate?: number | null;
  durationMs: number;
  multipv: number;
  cueTimes?: Record<string, number>;
}

export interface SceneReset { 
  type: "reset"; 
  id: string; 
  durationMs: number; 
}

export type Scene = SceneMain | SceneAlt | SceneReset;

export interface Timeline {
  meta: { 
    white: string; 
    black: string; 
    date?: string; 
    event?: string;
    result?: string;
    eco?: string;
  };
  scenes: Scene[];
  totalDurationMs: number;
}

export interface VoiceLine {
  id: string;
  text: string;
  durationMs?: number;
}

export interface RenderOptions {
  resolution: {
    width: number;
    height: number;
  };
  fps: number;
  audioDir: string;
  outputPath: string;
}
