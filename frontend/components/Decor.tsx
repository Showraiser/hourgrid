// Type and marks for the "botanical study" style.

/** Bold uppercase headline whose top half is cut and nudged, like a misregistered print. */
export function Sliced({ text, style }: { text: string; style?: React.CSSProperties }) {
  return (
    <span className="slice-wrap" data-text={text} style={style}>
      <span className="slice">{text}</span>
    </span>
  );
}

/** A small cross-stitch X. */
export function XMark({ size = 10, color = "currentColor" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 10 10" aria-hidden style={{ verticalAlign: "-1px" }}>
      <path d="M1.5 1.5L8.5 8.5M8.5 1.5L1.5 8.5" stroke={color} strokeWidth="2" strokeLinecap="square" />
    </svg>
  );
}

/** A barcode whose bars ARE the data: every hex nibble of the hash sets a bar width. */
export function Barcode({ hash, height = 32, label, color = "#a9c3ea" }: { hash: string; height?: number; label?: string; color?: string }) {
  const hex = (hash || "0x").replace(/^0x/, "").padEnd(32, "0");
  let x = 0;
  const bars: { x: number; w: number; o: number }[] = [];
  for (let i = 0; i < hex.length; i++) {
    const v = parseInt(hex[i], 16);
    const w = 1 + (v % 4);
    if (i % 2 === 0) bars.push({ x, w, o: 0.35 + (v / 15) * 0.65 });
    x += w + 1 + (v >> 2) * 0.5;
  }
  return (
    <div>
      <svg width="100%" height={height} viewBox={`0 0 ${x} ${height}`} preserveAspectRatio="none" aria-label={`barcode of ${hash}`} shapeRendering="crispEdges">
        {bars.map((b, i) => <rect key={i} x={b.x} y="0" width={b.w} height={height} fill={color} opacity={b.o} />)}
      </svg>
      {label && (
        <div className="tiny muted" style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
          <span className="it">{label}</span><span>{hash.slice(0, 10)}…{hash.slice(-6)}</span>
        </div>
      )}
    </div>
  );
}

export function WarnIcon({ size = 14 }: { size?: number; color?: string }) {
  return <XMark size={size} color="#b9b3e6" />;
}
