export function nextReplayIndex(current: number, length: number): number {
  if (length <= 0) return -1;
  return Math.min(current + 1, length - 1);
}
