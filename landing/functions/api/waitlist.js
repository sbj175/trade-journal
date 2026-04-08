export async function onRequestPost(context) {
    const BACKEND_URL = context.env.BACKEND_URL || "https://web-production-a042b.up.railway.app";

    try {
        const body = await context.request.json();

        // Edge-level honeypot check — reject silently before proxying
        if (body.website) {
            return new Response(JSON.stringify({ status: "ok" }), {
                headers: { "Content-Type": "application/json" },
            });
        }

        const resp = await fetch(`${BACKEND_URL}/api/waitlist`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: body.email, website: "" }),
        });

        const data = await resp.text();
        return new Response(data, {
            status: resp.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        return new Response(JSON.stringify({ detail: "Server error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
}
