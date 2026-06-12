<script setup>
import { ref, nextTick, onBeforeUnmount } from 'vue'
import { sendChatMessage } from '@/api/chat'
import { useUserStore } from '@/stores/modules/user'
import ChatMessage from './ChatMessage.vue'
import ChatInput from './ChatInput.vue'

const userStore = useUserStore()

// 消息列表: { id, role, content, shopCards, isStreaming }
const messages = ref([])
const isStreaming = ref(false)
const sessionId = ref(null)
const abortController = ref(null)

// 获取用户位置
function getUserLocation() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve({ longitude: null, latitude: null })
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ longitude: pos.coords.longitude, latitude: pos.coords.latitude }),
      () => resolve({ longitude: null, latitude: null }),
      { timeout: 5000 }
    )
  })
}

async function handleSend(text) {
  if (isStreaming.value) return

  // 添加用户消息
  messages.value.push({
    id: Date.now(),
    role: 'user',
    content: text
  })

  // 添加 AI 占位消息
  const aiMsg = {
    id: Date.now() + 1,
    role: 'assistant',
    content: '',
    shopCards: [],
    isStreaming: true
  }
  messages.value.push(aiMsg)
  isStreaming.value = true

  await nextTick()
  scrollToBottom()

  // 获取位置
  const { longitude, latitude } = await getUserLocation()

  // 发送 SSE 请求
  abortController.value = sendChatMessage(
    {
      query: text,
      sessionId: sessionId.value,
      userId: userStore.userInfo?.id || null,
      longitude,
      latitude
    },
    {
      onText(chunk) {
        aiMsg.content += chunk
        scrollToBottom()
      },
      onShopCard(data) {
        aiMsg.shopCards.push(data)
      },
      onDone() {
        aiMsg.isStreaming = false
        isStreaming.value = false
        scrollToBottom()
      },
      onError(msg) {
        if (!aiMsg.content) {
          aiMsg.content = msg || '抱歉，服务暂时不可用'
          aiMsg.error = true
        }
        aiMsg.isStreaming = false
        isStreaming.value = false
      }
    }
  )
}

// 重试最后一条消息
function retryLastMessage() {
  const lastUserMsg = [...messages.value].reverse().find(m => m.role === 'user')
  if (!lastUserMsg) return
  // 移除最后的 AI 错误消息（从后往前找第一个匹配的位置）
  let lastAiIdx = -1
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i].role === 'assistant' && messages.value[i].error) {
      lastAiIdx = i
      break
    }
  }
  if (lastAiIdx >= 0) messages.value.splice(lastAiIdx, 1)
  handleSend(lastUserMsg.content)
}

function scrollToBottom() {
  nextTick(() => {
    const el = document.querySelector('.chat-messages')
    if (el) el.scrollTop = el.scrollHeight
  })
}

// 组件卸载时取消请求
onBeforeUnmount(() => {
  abortController.value?.abort()
})
</script>

<template>
  <div class="chat-view">
    <!-- 顶部导航栏 -->
    <div class="chat-header">
      <span class="chat-title">AI 导购</span>
      <span class="chat-subtitle">智能推荐本地好店</span>
    </div>

    <!-- 消息列表 -->
    <div class="chat-messages">
      <div v-if="messages.length === 0" class="chat-empty">
        <p>👋 你好！我是你的 AI 导购助手</p>
        <p class="chat-empty-hint">试试问我：</p>
        <div class="chat-suggestions">
          <el-button size="small" @click="handleSend('推荐附近的火锅')">推荐附近的火锅</el-button>
          <el-button size="small" @click="handleSend('春熙路人均100以内的川菜')">春熙路人均100以内的川菜</el-button>
          <el-button size="small" @click="handleSend('适合约会的西餐厅')">适合约会的西餐厅</el-button>
        </div>
      </div>

      <ChatMessage
        v-for="msg in messages"
        :key="msg.id"
        :message="msg"
        @retry="retryLastMessage"
      />
    </div>

    <!-- 底部输入栏 -->
    <ChatInput :disabled="isStreaming" @send="handleSend" />
  </div>
</template>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f5f5f5;
}
.chat-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 0 8px;
  background: #fff;
  border-bottom: 1px solid #eee;
}
.chat-title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}
.chat-subtitle {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px 0;
}
.chat-empty {
  text-align: center;
  padding: 60px 20px;
  color: #606266;
}
.chat-empty-hint {
  margin-top: 12px;
  font-size: 14px;
  color: #909399;
}
.chat-suggestions {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  justify-content: center;
  flex-wrap: wrap;
}
</style>
