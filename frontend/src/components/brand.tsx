/** The user supplied this static MIPT emblem. Never animate the artwork. */
export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <span className={`brand-identity ${compact ? "compact" : ""}`}>
      <span className="brand-emblem">
        <img src="/brand/mipt-emblem.jpg" alt="МФТИ" width="80" height="80" />
      </span>
      <span className="brand-name">
        Смена<small>МФТИ</small>
      </span>
    </span>
  );
}
