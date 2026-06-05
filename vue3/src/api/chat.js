import { consumeSSE } from '@/utils/sse'

/**
 * 发送对话消息并流式接收回复。
 *
 * @param {object} params - { query, sessionId?, longitude?, latitude? }
 * @param {object} callbacks - { onText, onShopCard, onDone, onError }
 * @returns {AbortController}
 */
export function sendChatMessage(params, callbacks) {
  return consumeSSE('/api/chat/stream', {
    query: params.query,
    sessionId: params.sessionId || null,
    longitude: params.longitude || null,
    latitude: params.latitude || null
  }, callbacks)
}
