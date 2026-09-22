import type { JsonValue } from "../lib/api";

export function JsonView({
  value,
  depth = 0,
}: {
  value: JsonValue;
  depth?: number;
}) {
  if (value === null || typeof value !== "object") {
    return <span>{value === null ? "없음" : String(value)}</span>;
  }

  if (depth >= 2) {
    return (
      <pre className="json-inline">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }

  if (Array.isArray(value)) {
    return value.length ? (
      <ul className="json-list">
        {value.map((item, index) => (
          <li key={index}>
            <JsonView value={item} depth={depth + 1} />
          </li>
        ))}
      </ul>
    ) : (
      <span>없음</span>
    );
  }

  const entries = Object.entries(value);
  return entries.length ? (
    <dl className={depth === 0 ? "json" : "json json-nested"}>
      {entries.map(([key, item]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>
            <JsonView value={item} depth={depth + 1} />
          </dd>
        </div>
      ))}
    </dl>
  ) : (
    <span>없음</span>
  );
}
