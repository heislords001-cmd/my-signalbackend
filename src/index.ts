import { handleUpdate } from "./bot";
import { analyzeSymbol } from "./signalengine";

export interface Env {
  BOT_TOKEN: string;
  TWELVE_DATA_API_KEY: string;
  SIGNAL_CHANNEL_ID: string;
}

const TELEGRAM_API = "https://api.telegram.org/bot";
const MAIN_SYMBOLS = ["XAU/USD", "BTC/USD", "EUR/USD"];

const lastSignals: Record<string, string> = {};

async function sendToChannel(token: string, channelId: string, signal: any) {
  const emoji = signal.direction === "BUY" ? "🟢" : "🔴";
  const arrow = signal.direction === "BUY" ? "📈" : "📉";

  const message = `${emoji} *${signal.direction} ${signal.symbol}* ${arrow}\n\n*Entry:* \`${signal.entry}\`\n*Stop Loss:* \`${signal.stopLoss}\`\n*Take Profit:* \`${signal.takeProfit}\`\n*Risk/Reward:* 1:${signal.riskReward}\n\n*Confidence:* ${signal.confidence}%\n\n*Why:*\n${signal.reasons.map((r: string) => `• ${r}`).join("\n")}`;

  await fetch(`${TELEGRAM_API}${token}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: channelId,
      text: message,
      parse_mode: "Markdown",
      disable_web_page_preview: true,
    }),
  });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return new Response("OK", { status: 200 });
    }

    if (url.pathname === "/webhook" && request.method === "POST") {
      try {
        const update: any = await request.json();
        ctx.waitUntil(handleUpdate(update, env.BOT_TOKEN, env.TWELVE_DATA_API_KEY));
        return new Response("OK", { status: 200 });
      } catch (error) {
        console.error("Webhook error:", error);
        return new Response("Error", { status: 500 });
      }
    }

    return new Response("Not found", { status: 404 });
  },

  async scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext): Promise<void> {
    // DEBUG: confirm the env bindings are actually available
    console.log(
      `[DEBUG ENV] BOT_TOKEN=${env.BOT_TOKEN ? "set" : "MISSING"} TWELVE_DATA_API_KEY=${env.TWELVE_DATA_API_KEY ? "set" : "MISSING"} SIGNAL_CHANNEL_ID=${env.SIGNAL_CHANNEL_ID ? "set" : "MISSING"}`
    );

    for (const symbol of MAIN_SYMBOLS) {
      try {
        const signal = await analyzeSymbol(env.TWELVE_DATA_API_KEY, symbol);

        if (!signal) {
          delete lastSignals[symbol];
          continue;
        }

        const signalKey = `${signal.direction}-${signal.entry}`;
        if (lastSignals[symbol] === signalKey) {
          continue;
        }

        await sendToChannel(env.BOT_TOKEN, env.SIGNAL_CHANNEL_ID, signal);
        lastSignals[symbol] = signalKey;

        console.log(`Sent ${signal.direction} signal for ${symbol}`);
      } catch (error) {
        if (error instanceof Error) {
          console.error(`FAILED ${symbol}: ${error.message}`);
        } else {
          console.error(`FAILED ${symbol}: ${String(error)}`);
        }
      }
    }
  },
};