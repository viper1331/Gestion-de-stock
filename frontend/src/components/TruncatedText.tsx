import { useMemo, useState } from "react";

export function TruncatedText({
  text,
  maxLength,
  className
}: {
  text: string;
  maxLength: number;
  className?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const { truncated, isTruncated } = useMemo(() => {
    if (text.length <= maxLength) {
      return { truncated: text, isTruncated: false };
    }
    return { truncated: `${text.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`, isTruncated: true };
  }, [maxLength, text]);

  return (
    <span className={className}>
      {expanded || !isTruncated ? text : truncated}
      {isTruncated ? (
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          className="ml-2 text-[11px] font-semibold text-indigo-300 hover:text-indigo-200"
        >
          {expanded ? "Voir moins" : "Voir plus"}
        </button>
      ) : null}
    </span>
  );
}
