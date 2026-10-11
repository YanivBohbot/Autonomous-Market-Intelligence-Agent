// User-side bubble for the words GPT-Live is hearing right now. It is a
// transient caption: once the turn ends it clears, and the committed user
// message arrives through the history refresh.
export function LiveCaptionBubble({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="flex justify-end px-4 pb-2">
      <div
        role="status"
        aria-label="You are speaking"
        aria-live="polite"
        className="max-w-[80%] rounded-2xl rounded-br-sm border border-dashed border-terminal-accent/50 bg-terminal-accent/10 px-3.5 py-2 text-sm italic text-terminal-text"
      >
        <span aria-hidden="true" className="mr-1.5">🎤</span>
        {text}
        <span aria-hidden="true" className="ml-1 animate-pulse">▍</span>
      </div>
    </div>
  );
}
