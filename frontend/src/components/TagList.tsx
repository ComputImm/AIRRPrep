export function TagList({ tags }: { tags: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {tags.map((t) => (
        <span
          key={t}
          className="rounded-full bg-accent/60 px-2.5 py-0.5 text-xs font-medium text-accent-foreground ring-1 ring-inset ring-border/60"
        >
          {t}
        </span>
      ))}
    </div>
  );
}
