interface ComingSoonPageProps {
  title: string;
  description: string;
}

export function ComingSoonPage({ title, description }: ComingSoonPageProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center">
      <h1 className="font-mono text-lg font-semibold text-terminal-text">{title}</h1>
      <p className="max-w-md font-mono text-sm text-terminal-muted">{description}</p>
      <span className="mt-2 rounded border border-terminal-border bg-terminal-panel px-3 py-1 font-mono text-[10px] uppercase tracking-widest text-terminal-muted">
        Bientôt disponible
      </span>
    </div>
  );
}
