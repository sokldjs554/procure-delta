const shapes: Record<string, string> = {
  inbox: "M4 4h16v16H4z M4 13h5l2 3h2l2-3h5",
  pipeline: "M5 5h5v5H5z M14 14h5v5h-5z M10 7h7v7 M7 10v7h7",
  watch: "M6 3h12v18l-6-4-6 4z",
  bell: "M5 17h14l-2-3V9a5 5 0 0 0-10 0v5z M10 21h4",
  profile: "M4 21V7l8-4v18 M12 10h8v11 M8 8v1 M8 12v1 M8 16v1 M16 14h1 M16 17h1 M2 21h20",
  chart: "M4 4v16h17 M8 15l4-5 4 3 5-7",
  arrow: "M4 12h16 M14 6l6 6-6 6",
};

export function UiIcon({ name, className }: { name: string; className?: string }) {
  return <svg className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={shapes[name] ?? shapes.arrow} /></svg>;
}
