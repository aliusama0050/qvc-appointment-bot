export default {
  async fetch(request) {
    const url = new URL(request.url);
    
    // Only proxy /bot* paths (Telegram Bot API)
    if (!url.pathname.startsWith("/bot")) {
      return new Response("Telegram API Proxy. Use /bot<token>/<method>", {
        status: 200
      });
    }

    const telegramUrl = "https://api.telegram.org" + url.pathname + url.search;

    // Build clean headers — must NOT forward Host/CF headers
    const headers = new Headers();
    const contentType = request.headers.get("Content-Type");
    if (contentType) {
      headers.set("Content-Type", contentType);
    }

    const init = {
      method: request.method,
      headers: headers,
    };

    if (request.method === "POST") {
      init.body = await request.arrayBuffer();
    }

    const response = await fetch(telegramUrl, init);

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: {
        "Content-Type": response.headers.get("Content-Type") || "application/json",
        "Access-Control-Allow-Origin": "*",
      },
    });
  },
};