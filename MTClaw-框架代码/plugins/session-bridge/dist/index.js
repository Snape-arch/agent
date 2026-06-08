/**
 * Session Bridge Provider Plugin for OpenClaw >= 2026.3.24
 *
 * Injects x-openclaw-session-key header when a stable sessionKey is available.
 * Falls back to x-openclaw-session-id when the runtime only exposes sessionId.
 *
 * Two hooks work together to cover all transport paths:
 *
 * - wrapStreamFn: wraps the HTTP stream function (streamSimple) to inject the
 *   header on every call. This is the primary path for openai-completions API.
 *
 * - resolveTransportTurnState: returns headers for WebSocket and Responses API
 *   transports, which call this hook natively.
 *
 * The hookAliases field tells OpenClaw that this plugin handles the
 * "function_router" provider, so the hooks fire for that provider's requests.
 */
function pickSessionKey(source) {
    return typeof source?.sessionKey === "string" ? source.sessionKey.trim() : "";
}
function pickSessionId(source) {
    return typeof source?.sessionId === "string" ? source.sessionId.trim() : "";
}
function buildSessionHeaders(source) {
    const sessionKey = pickSessionKey(source);
    if (sessionKey) {
        return { "x-openclaw-session-key": sessionKey };
    }
    const sessionId = pickSessionId(source);
    if (sessionId) {
        return { "x-openclaw-session-id": sessionId };
    }
    return null;
}
const sessionBridgePlugin = {
    id: "session-bridge",
    name: "Session Bridge",
    description: "Injects session headers into function_router requests",
    register(api) {
        api.logger.info?.("[session-bridge] registering provider");
        // id must literally equal the configured provider id ("function_router") so
        // OpenClaw 2026.5.18 finds this plugin via matchesProviderLiteralId when the
        // provider config has api="openai-completions" (apiOwnerHint branch). hookAliases
        // is retained for backwards compatibility with 2026.4.14's matcher path.
        api.registerProvider({
            id: "function_router",
            label: "Function Router (Session Header)",
            aliases: ["openai-session-header"],
            hookAliases: ["function_router"],
            auth: [],
            /**
             * Wraps the base stream function to inject the session header.
             * On 2026.5.18 the per-call `options` argument carries `sessionId`;
             * on 2026.4.14 `options` carries `sessionKey` and/or `sessionId`.
             */
            wrapStreamFn(ctx) {
                const baseStreamFn = ctx.streamFn;
                if (!baseStreamFn)
                    return null;
                return (model, context, options) => {
                    const sessionHeaders = buildSessionHeaders(options);
                    if (sessionHeaders) {
                        options = {
                            ...options,
                            headers: {
                                ...options?.headers,
                                ...sessionHeaders,
                            },
                        };
                    }
                    return baseStreamFn(model, context, options);
                };
            },
            /**
             * Returns transport turn state headers for WebSocket / Responses API paths
             * (e.g. openai-responses), which call this hook natively per turn.
             */
            resolveTransportTurnState(ctx) {
                const sessionHeaders = buildSessionHeaders(ctx);
                if (!sessionHeaders)
                    return null;
                return { headers: sessionHeaders };
            },
        });
    },
};
export default sessionBridgePlugin;
