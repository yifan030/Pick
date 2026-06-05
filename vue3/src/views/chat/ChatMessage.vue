<script setup>
import ShopCard from './ShopCard.vue'

defineProps({
  message: {
    type: Object,
    required: true
    // { role: 'user' | 'assistant', content: string, shopCards?: [...], isStreaming?: boolean }
  }
})

defineEmits(['retry'])
</script>

<template>
  <!-- 用户消息 -->
  <div v-if="message.role === 'user'" class="chat-msg chat-msg-user">
    <div class="msg-bubble msg-bubble-user">
      {{ message.content }}
    </div>
  </div>

  <!-- AI 消息 -->
  <div v-else class="chat-msg chat-msg-ai">
    <div class="msg-avatar">🤖</div>
    <div class="msg-body">
      <div class="msg-bubble msg-bubble-ai">
        <span class="msg-text">{{ message.content }}</span>
        <span v-if="message.isStreaming" class="cursor-blink">|</span>
      </div>

      <!-- 店铺卡片列表 -->
      <div v-if="message.shopCards?.length" class="shop-cards-list">
        <ShopCard
          v-for="shop in message.shopCards"
          :key="shop.shop_id"
          :shop="shop"
        />
      </div>

      <!-- AI 消息错误/重试 -->
      <div v-if="message.error" class="msg-retry">
        <el-button size="small" type="warning" @click="$emit('retry')">
          重试
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-msg {
  display: flex;
  margin-bottom: 16px;
  padding: 0 16px;
}
.chat-msg-user {
  justify-content: flex-end;
}
.chat-msg-ai {
  justify-content: flex-start;
}
.msg-avatar {
  width: 36px;
  height: 36px;
  font-size: 20px;
  line-height: 36px;
  text-align: center;
  margin-right: 8px;
  flex-shrink: 0;
}
.msg-body {
  max-width: 80%;
}
.msg-bubble {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 15px;
  line-height: 1.6;
  word-break: break-word;
}
.msg-bubble-user {
  background: #409eff;
  color: #fff;
  border-bottom-right-radius: 4px;
}
.msg-bubble-ai {
  background: #f4f4f5;
  color: #303133;
  border-bottom-left-radius: 4px;
}
.cursor-blink {
  animation: blink 1s infinite;
}
@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}
.shop-cards-list {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.msg-retry {
  margin-top: 8px;
}
</style>
