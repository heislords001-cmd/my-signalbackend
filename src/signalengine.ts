import { fetchCandles } from "./datafetcher";
import {
  calculateEMA,
  calculateRSI,
  calculateATR,
  calculateADX,
  getLatest,
} from "./indicators";

export interface Signal {
  symbol: string;
  direction: "BUY" | "SELL";
  entry: number;
  stopLoss: number;
  takeProfit: number;
  riskReward: number;
  confidence: number;
  reasons: string[];
  timestamp: string;
}

export async function analyzeSymbol(
  apiKey: string,
  symbol: string
): Promise<Signal | null> {
  const [candles15m, candles1h, candles4h] = await Promise.all([
    fetchCandles(apiKey, symbol, "15min", 200),
    fetchCandles(apiKey, symbol, "1h", 200),
    fetchCandles(apiKey, symbol, "4h", 200),
  ]);

  const c15 = [...candles15m].reverse();
  const c1h = [...candles1h].reverse();
  const c4h = [...candles4h].reverse();

  const closes15 = c15.map((c) => c.close);
  const closes1h = c1h.map((c) => c.close);
  const closes4h = c4h.map((c) => c.close);

  const ema20_15 = getLatest(calculateEMA(closes15, 20));
  const ema50_15 = getLatest(calculateEMA(closes15, 50));
  const rsi15 = getLatest(calculateRSI(closes15, 14));
  const atr15 = getLatest(calculateATR(c15, 14));
  const adx15 = getLatest(calculateADX(c15, 14));

  const ema20_1h = getLatest(calculateEMA(closes1h, 20));
  const ema50_1h = getLatest(calculateEMA(closes1h, 50));

  const ema20_4h = getLatest(calculateEMA(closes4h, 20));
  const ema50_4h = getLatest(calculateEMA(closes4h, 50));

  const currentPrice = closes15[closes15.length - 1];

  const reasons: string[] = [];
  let buyScore = 0;
  let sellScore = 0;

  if (ema20_4h > ema50_4h) {
    buyScore++;
    reasons.push("4H trend is bullish (EMA20 > EMA50)");
  } else if (ema20_4h < ema50_4h) {
    sellScore++;
    reasons.push("4H trend is bearish (EMA20 < EMA50)");
  }

  if (ema20_1h > ema50_1h) {
    buyScore++;
    reasons.push("1H confirms bullish structure");
  } else if (ema20_1h < ema50_1h) {
    sellScore++;
    reasons.push("1H confirms bearish structure");
  }

  if (ema20_15 > ema50_15 && rsi15 > 50 && rsi15 < 70) {
    buyScore++;
    reasons.push(`15M bullish crossover with RSI at ${rsi15.toFixed(1)}`);
  } else if (ema20_15 < ema50_15 && rsi15 < 50 && rsi15 > 30) {
    sellScore++;
    reasons.push(`15M bearish crossover with RSI at ${rsi15.toFixed(1)}`);
  }

  if (adx15 < 25) {
    return null;
  }
  reasons.push(`ADX is ${adx15.toFixed(1)} — trend confirmed`);

  let direction: "BUY" | "SELL" | null = null;
  if (buyScore === 3) direction = "BUY";
  else if (sellScore === 3) direction = "SELL";

  if (!direction) {
    return null;
  }

  const slDistance = atr15 * 1.5;
  const tpDistance = slDistance * 3;

  const stopLoss = direction === "BUY" ? currentPrice - slDistance : currentPrice + slDistance;
  const takeProfit = direction === "BUY" ? currentPrice + tpDistance : currentPrice - tpDistance;

  const confidence = Math.min(100, Math.round(60 + adx15 * 0.5));

  return {
    symbol,
    direction,
    entry: parseFloat(currentPrice.toFixed(5)),
    stopLoss: parseFloat(stopLoss.toFixed(5)),
    takeProfit: parseFloat(takeProfit.toFixed(5)),
    riskReward: 3,
    confidence,
    reasons,
    timestamp: new Date().toISOString(),
  };
}