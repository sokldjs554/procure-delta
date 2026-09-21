import type { JsonValue } from "../lib/api";

export function JsonView({ value }: { value: JsonValue }) {
  if (value === null || typeof value !== "object") {
    return <span>{value === null ? "없음" : String(value)}</span>;
  }

  if (Array.isArray(value)) {
    return value.length ? (
      <ul>
        {value.map((item, index) => (
          <li key={index}>
            <JsonView value={item} />
          </li>
        ))}
      </ul>
    ) : (
      <span>없음</span>
    );
  }

  const entries = Object.entries(value);
  return entries.length ? (
    <dl className="json">
      {entries.map(([key, item]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>
            <JsonView value={item} />
          </dd>
        </div>
      ))}
    </dl>
  ) : (
    <span>없음</span>
  );
}
