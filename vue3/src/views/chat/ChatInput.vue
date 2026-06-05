<script setup>
import { ref } from 'vue'

const emit = defineEmits(['send'])
const inputText = ref('')
const isSending = defineProps({
  disabled: { type: Boolean, default: false }
})

function handleSend() {
  const text = inputText.value.trim()
  if (!text || isSending.disabled) return
  emit('send', text)
  inputText.value = ''
}

function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <div class="chat-input-bar">
    <el-input
      v-model="inputText"
      type="textarea"
      :rows="1"
      :autosize="{ minRows: 1, maxRows: 4 }"
      placeholder="输入您想找的店铺或优惠..."
      :disabled="disabled"
      @keydown="handleKeydown"
    />
    <el-button
      type="primary"
      :disabled="disabled || !inputText.trim()"
      @click="handleSend"
    >
      发送
    </el-button>
  </div>
</template>

<style scoped>
.chat-input-bar {
  display: flex;
  gap: 10px;
  padding: 12px 16px;
  background: #fff;
  border-top: 1px solid #eee;
  align-items: flex-end;
}
.chat-input-bar :deep(.el-textarea__inner) {
  resize: none;
}
</style>
