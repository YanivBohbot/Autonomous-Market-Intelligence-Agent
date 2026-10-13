// Chat starter suggestions per page (shown before the first message only).

export type StarterSuggestion = { title: string; message: string };

export const RESEARCH_STARTERS: StarterSuggestion[] = [
  { title: "Compare NVDA vs AMD", message: "Compare NVDA vs AMD" },
  { title: "Triggered watchlist alerts", message: "Which clients have triggered watchlist alerts?" },
  { title: "What if Margaret sold half her NVDA?", message: "What if Margaret Collins sold half her NVDA?" },
  { title: "Who holds Tesla?", message: "Which clients hold Tesla?" },
];

export const CLIENT_STARTERS: StarterSuggestion[] = [
  { title: "Summarize this portfolio", message: "Summarize this client's portfolio" },
  { title: "Watchlist alerts", message: "Any watchlist alerts for this client?" },
  { title: "Sell half the largest position?", message: "What if this client sold half of their largest position?" },
];
