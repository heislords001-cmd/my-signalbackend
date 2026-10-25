export interface Candle {
  datetime: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export async function fetchCandles(
  apiKey: string,
  symbol: string,
  interval: string,
  outputsize: number = 100
): Promise<Candle[]> {
  // DEBUG: log the key details so we can see what Cloudflare is actually sending
  console.log(
    `[DEBUG KEY] symbol=${symbol} interval=${interval} length=${apiKey?.length} start=${apiKey?.slice(0, 8)} end=${apiKey?.slice(-4)}`
  );

  const url = `https://api.twelvedata.com/time_series?symbol=${symbol}&interval=${interval}&outputsize=${outputsize}&apikey=${apiKey}`;

  const response = await fetch(url);
  const text = await response.text();

  console.log(
    `[Twelve Data] ${symbol} ${interval} status=${response.status} body=${text.slice(0, 300)}`
  );

  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(`Invalid JSON: ${text.slice(0, 200)}`);
  }

  if (data.status === "error") {
    throw new Error(`Twelve Data error: ${data.message || "Unknown"}`);
  }

  if (!data.values || data.values.length === 0) {
    throw new Error(`No data for ${symbol} at ${interval}`);
  }

  return data.values.map((candle: any) => ({
    datetime: candle.datetime,
    open: parseFloat(candle.open),
    high: parseFloat(candle.high),
    low: parseFloat(candle.low),
    close: parseFloat(candle.close),
    volume: parseInt(candle.volume || "0"),
  }));
}