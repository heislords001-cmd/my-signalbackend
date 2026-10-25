import { analyzeSymbol } from "./signalengine";

const TELEGRAM_API = "https://api.telegram.org/bot";

async function sendMessage(token: string, chatId: number, text: string, parseMode: string = "Markdown") {
  await fetch(`${TELEGRAM_API}${token}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text: text,
      parse_mode: parseMode,
      disable_web_page_preview: true,
    }),
  });
}

async function editMessage(token: string, chatId: number, messageId: number, text: string) {
  await fetch(`${TELEGRAM_API}${token}/editMessageText`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      message_id: messageId,
      text: text,
      parse_mode: "Markdown",
      disable_web_page_preview: true,
    }),
  });
}

function formatSignal(signal: any): string {
  const emoji = signal.direction === "BUY" ? "🟢" : "🔴";
  const arrow = signal.direction === "BUY" ? "📈" : "📉";
  return `${emoji} *${signal.direction} ${signal.symbol}* ${arrow}\n\n*Entry:* \`${signal.entry}\`\n*Stop Loss:* \`${signal.stopLoss}\`\n*Take Profit:* \`${signal.takeProfit}\`\n*Risk/Reward:* 1:${signal.riskReward}\n\n*Confidence:* ${signal.confidence}%\n\n*Why:*\n${signal.reasons.map((r: string) => `• ${r}`).join("\n")}`;
}

export async function handleUpdate(update: any, token: string, twelveDataKey: string) {
  const message = update.message;
  if (!message || !message.text) return;

  const chatId = message.chat.id;
  const text = message.text.trim();

  if (text === "/start") {
    await sendMessage(token, chatId,
      `*Welcome to the Signal Bot* 🤖\n\nI scan XAU/USD, BTC/USD, and EUR/USD every 15 minutes and alert you when there's a high-confluence setup.\n\nCommands:\n/signal XAUUSD — Get a signal\n/scan — Scan all main markets\n/price XAUUSD — Get current price\n/help — Show this menu`
    );
    return;
  }

  if (text === "/help") {
    await sendMessage(token, chatId,
      `*Available Commands*\n\n/signal XAUUSD — Get signal for gold\n/signal BTCUSD — Get signal for Bitcoin\n/signal EURUSD — Get signal for Euro\n/scan — Scan all three main markets\n/price XAUUSD — Get current price\n\n*How signals work:*\nI only fire when 15M, 1H, and 4H all align. If they don't, I stay silent. No signal = no trade.`
    );
    return;
  }

  if (text.startsWith("/price")) {
    const args = text.replace("/price", "").trim().toUpperCase();
    if (!args) {
      await sendMessage(token, chatId, "Usage: `/price XAUUSD`");
      return;
    }
    const formatted = args.includes("/") ? args : `${args.slice(0, 3)}/${args.slice(3)}`;

    try {
      const url = `https://api.twelvedata.com/price?symbol=${formatted}&apikey=${twelveDataKey}`;
      const res = await fetch(url);
      const data = await res.json();
      if (data.price) {
        await sendMessage(token, chatId, `💵 *${formatted}*: \`${parseFloat(data.price).toFixed(5)}\``);
      } else {
        await sendMessage(token, chatId, `❌ Could not fetch price for ${formatted}.`);
      }
    } catch {
      await sendMessage(token, chatId, "❌ Error fetching price.");
    }
    return;
  }

  if (text.startsWith("/signal")) {
    const args = text.replace("/signal", "").trim().toUpperCase();
    if (!args) {
      await sendMessage(token, chatId, "Usage: `/signal XAUUSD`");
      return;
    }
    const formatted = args.includes("/") ? args : `${args.slice(0, 3)}/${args.slice(3)}`;

    const loading = await fetch(`${TELEGRAM_API}${token}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text: `🔍 Analyzing ${formatted}...` }),
    });
    const loadingData = await loading.json();
    const loadingMsgId = loadingData.result?.message_id;

    try {
      const signal = await analyzeSymbol(twelveDataKey, formatted);
      if (signal) {
        if (loadingMsgId) await editMessage(token, chatId, loadingMsgId, formatSignal(signal));
      } else {
        if (loadingMsgId) await editMessage(token, chatId, loadingMsgId,
          `⚪ *No signal for ${formatted}*\n\nThe timeframes are not aligned, or the market is ranging. Wait for the next candle.`
        );
      }
    } catch {
      if (loadingMsgId) await editMessage(token, chatId, loadingMsgId, `❌ Error analyzing ${formatted}.`);
    }
    return;
  }

  if (text === "/scan") {
    const loading = await fetch(`${TELEGRAM_API}${token}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text: "🔍 Scanning XAU/USD, BTC/USD, EUR/USD..." }),
    });
    const loadingData = await loading.json();
    const loadingMsgId = loadingData.result?.message_id;

    const symbols = ["XAU/USD", "BTC/USD", "EUR/USD"];
    const results: string[] = [];

    for (const symbol of symbols) {
      try {
        const signal = await analyzeSymbol(twelveDataKey, symbol);
        if (signal) {
          results.push(formatSignal(signal));
        } else {
          results.push(`⚪ *${symbol}* — no signal (timeframes not aligned)`);
        }
      } catch {
        results.push(`❌ *${symbol}* — error fetching data`);
      }
    }

    if (loadingMsgId) await editMessage(token, chatId, loadingMsgId, results.join("\n\n─────────────\n\n"));
    return;
  }
}