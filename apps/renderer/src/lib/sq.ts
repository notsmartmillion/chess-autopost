export const fileToX = (f: string) => f.charCodeAt(0) - 'a'.charCodeAt(0);
export const rankToY = (r: string) => 8 - parseInt(r,10);
export const sqToRC = (sq: string) => [fileToX(sq[0]!), rankToY(sq[1]!)];
export const arrowPath = (from: string, to: string, size=512) => {
  const cell = size/8;
  const [fx, fy] = sqToRC(from), [tx, ty] = sqToRC(to);
  const x1 = fx*cell + cell/2, y1 = fy*cell + cell/2;
  const x2 = tx*cell + cell/2, y2 = ty*cell + cell/2;
  return {x1, y1, x2, y2};
};
