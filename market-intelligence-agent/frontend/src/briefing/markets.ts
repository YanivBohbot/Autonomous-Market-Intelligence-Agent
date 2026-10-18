export interface MarketDefinition {
  id: string;
  label: string;
  title: string;
  instruments: { symbol: string; name: string }[];
}

export const MARKETS: MarketDefinition[] = [
  { id: "us", label: "U.S.", title: "United States", instruments: [["^GSPC", "S&P 500"], ["^DJI", "Dow Jones"], ["^IXIC", "Nasdaq"], ["^RUT", "Russell 2000"], ["^NYA", "NYSE Composite"], ["^MID", "S&P MidCap 400"], ["^VIX", "VIX"]].map(([symbol, name]) => ({ symbol, name })) },
  { id: "europe", label: "Europe", title: "Europe", instruments: [["^GDAXI", "DAX"], ["^FTSE", "FTSE 100"], ["^FCHI", "CAC 40"], ["^STOXX50E", "Euro Stoxx 50"], ["^IBEX", "IBEX 35"], ["^SSMI", "SMI"], ["^AEX", "AEX"]].map(([symbol, name]) => ({ symbol, name })) },
  { id: "asia", label: "Asia", title: "Asia", instruments: [["^N225", "Nikkei 225"], ["^HSI", "Hang Seng"], ["000001.SS", "Shanghai Composite"], ["^KS11", "KOSPI"], ["^NSEI", "Nifty 50"], ["^BSESN", "BSE Sensex"], ["^AXJO", "ASX 200"], ["^TWII", "Taiwan Weighted"]].map(([symbol, name]) => ({ symbol, name })) },
  { id: "latin-america", label: "Latin America", title: "Latin America", instruments: [["^BVSP", "Ibovespa"], ["^MXX", "S&P/BMV IPC"], ["^MERV", "Merval"], ["ILF", "iShares Latin America 40 ETF"], ["ECH", "iShares MSCI Chile ETF"]].map(([symbol, name]) => ({ symbol, name })) },
  { id: "currencies", label: "Currencies", title: "Currencies", instruments: [["EURUSD=X", "EUR / USD"], ["JPY=X", "USD / JPY"], ["GBPUSD=X", "GBP / USD"], ["AUDUSD=X", "AUD / USD"], ["CAD=X", "USD / CAD"], ["CHF=X", "USD / CHF"], ["CNY=X", "USD / CNY"]].map(([symbol, name]) => ({ symbol, name })) },
  { id: "crypto", label: "Crypto", title: "Cryptocurrency", instruments: [["BTC-USD", "Bitcoin"], ["ETH-USD", "Ethereum"], ["SOL-USD", "Solana"], ["XRP-USD", "XRP"], ["BNB-USD", "BNB"], ["DOGE-USD", "Dogecoin"], ["ADA-USD", "Cardano"]].map(([symbol, name]) => ({ symbol, name })) },
];

export const SECTORS = [["XLK", "Technology"], ["XLF", "Financial Services"], ["XLV", "Healthcare"], ["XLE", "Energy"], ["XLY", "Consumer Cyclical"], ["XLP", "Consumer Defensive"], ["XLI", "Industrials"], ["XLC", "Communication Services"]].map(([symbol, name]) => ({ symbol, name }));
export const WATCHLIST = ["AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "META"];
