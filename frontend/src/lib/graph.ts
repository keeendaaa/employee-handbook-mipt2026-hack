/** Geometry is independent of viewport UI. All topic nodes remain readable up to
 * the backend limit of 32 topics; only the graph viewport may scroll sideways. */
export function graphLayout(ids: string[], questionCount: number, availableWidth: number) {
  const columns = Math.min(3, Math.max(1, Math.ceil(Math.sqrt(ids.length))));
  const rows = Math.ceil(ids.length / columns);
  const questionWidth = questionCount > 0 ? 300 : 0;
  const width = Math.max(640, availableWidth, columns * 244 + 64 + questionWidth);
  const height = Math.max(540, rows * 112 + 80, questionCount * 48 + 80);
  const topicWidth = width - questionWidth;
  return {width, height, centres: new Map(ids.map((id,i) => [id, {
    x: (topicWidth - columns * 244) / 2 + 122 + (i % columns) * 244,
    y: (height - rows * 112) / 2 + 56 + Math.floor(i / columns) * 112,
  }]))};
}
