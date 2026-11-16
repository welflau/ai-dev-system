/** 把 v 限制在 [min, max]。 */
export function clamp(v: number, min: number, max: number): number {
  return Math.min(Math.max(v, min), max);
}

/** 线性插值。 */
export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** 角度转弧度。 */
export function degToRad(deg: number): number {
  return (deg * Math.PI) / 180;
}
