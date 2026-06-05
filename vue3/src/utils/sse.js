/**
 * SSE 流式消费工具 — 用 fetch + ReadableStream 解析 PRD 格式的 SSE 事件。
 *
 * 事件类型: text, shop_card, done, error
 *
 * @param {string} url - 请求地址
 * @param {object} body - 请求体 JSON
 * @param {object} callbacks - { onText, onShopCard, onDone, onError }
 * @returns {AbortController} - 用于取消请求
 */
export function consumeSSE(url, body, callbacks = {}) {
  const controller = new AbortController()
  const { onText, onShopCard, onDone, onError } = callbacks

  fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `${localStorage.getItem('token') || ''}`
    },
    body: JSON.stringify(body),
    signal: controller.signal
  }).then(async (response) => {
    if (!response.ok) {
      onError?.('服务异常，请稍后重试')
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // SSE 数据行以 "data: " 开头
      const lines = buffer.split('\n')
      buffer = lines.pop() || '' // 保留未完成的行

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const jsonStr = line.slice(6)
          try {
            const event = JSON.parse(jsonStr)
            switch (event.type) {
              case 'text':
                onText?.(event.content)
                break
              case 'shop_card':
                onShopCard?.(event.data)
                break
              case 'done':
                onDone?.()
                break
              case 'error':
                onError?.(event.content)
                break
            }
          } catch {
            // 非 JSON 行忽略
          }
        }
      }
    }
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      onError?.('网络连接断开，请点击重试')
    }
  })

  return controller
}
