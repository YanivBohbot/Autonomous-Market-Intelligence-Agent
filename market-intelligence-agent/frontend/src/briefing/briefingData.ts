import {
  getBriefingIndices,
  getBriefingMovers,
  getBriefingNarrative,
  getBriefingNews,
  getBriefingSectors,
  getBriefingWatchlist,
  type BriefingData,
  type BriefingInstrument,
  type BriefingNewsItem,
} from "../lib/api";

type Movers = NonNullable<BriefingData["movers"]>;
type CacheEntry = { value: unknown; expiresAt: number };

const CACHE_MS = 5 * 60 * 1000;
const cache = new Map<string, CacheEntry>();
const pending = new Map<string, Promise<unknown>>();

function peek<T>(key: string): T | null {
  const entry = cache.get(key);
  if (!entry || entry.expiresAt <= Date.now()) {
    cache.delete(key);
    return null;
  }
  return entry.value as T;
}

async function load<T>(key: string, loader: () => Promise<T>): Promise<T> {
  const cached = peek<T>(key);
  if (cached !== null) return cached;
  const active = pending.get(key) as Promise<T> | undefined;
  if (active) return active;
  const request = loader()
    .then((value) => {
      cache.set(key, { value, expiresAt: Date.now() + CACHE_MS });
      return value;
    })
    .finally(() => pending.delete(key));
  pending.set(key, request);
  return request;
}

export function peekMarketIndices(market: string) {
  return peek<BriefingInstrument[]>(`indices:${market}`);
}

export function loadMarketIndices(market: string) {
  return load(`indices:${market}`, () => getBriefingIndices(market).then((response) => response.items));
}

export function peekSectors() {
  return peek<BriefingInstrument[]>("sectors");
}

export function loadSectors() {
  return load("sectors", () => getBriefingSectors().then((response) => response.items));
}

export function peekWatchlist() {
  return peek<BriefingInstrument[]>("watchlist");
}

export function loadWatchlist() {
  return load("watchlist", () => getBriefingWatchlist().then((response) => response.items));
}

export function peekMarketNews(market: string) {
  return peek<BriefingNewsItem[]>(`news:${market}`);
}

export function loadMarketNews(market: string) {
  return load(`news:${market}`, () => getBriefingNews(market).then((response) => response.items));
}

export function peekMarketNarrative(market: string) {
  return peek<string>(`narrative:${market}`);
}

export function loadMarketNarrative(market: string) {
  return load(`narrative:${market}`, () => getBriefingNarrative(market).then((response) => response.text));
}

export function peekMarketMovers(market: string) {
  return peek<Movers>(`movers:${market}`);
}

export function loadMarketMovers(market: string) {
  return load(`movers:${market}`, () => getBriefingMovers(market));
}

export function prefetchMarket(market: string) {
  void Promise.allSettled([
    loadMarketIndices(market),
    loadMarketNews(market),
    loadMarketMovers(market),
  ]);
}
