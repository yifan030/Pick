<script setup>
import { ref } from 'vue'
import { getShopById } from '@/api/shop'

const props = defineProps({
  shop: { type: Object, required: true }
})

const showDetail = ref(false)
const shopDetail = ref(null)
const loading = ref(false)

function parseTags(tags) {
  if (!tags) return []
  if (Array.isArray(tags)) return tags
  try {
    const parsed = JSON.parse(tags)
    return Array.isArray(parsed) ? parsed : [tags]
  } catch {
    return tags.split(',').map(t => t.trim()).filter(Boolean)
  }
}

async function openDetail() {
  if (shopDetail.value) {
    showDetail.value = true
    return
  }
  loading.value = true
  try {
    const res = await getShopById(props.shop.shop_id)
    shopDetail.value = res.data
    showDetail.value = true
  } catch {
    // 降级：用已有数据展示
    shopDetail.value = props.shop
    showDetail.value = true
  } finally {
    loading.value = false
  }
}

function formatScore(score) {
  if (!score) return '暂无评分'
  const s = score > 10 ? (score / 10) : score
  return s.toFixed(1) + '分'
}

function formatPrice(price) {
  if (!price) return ''
  return '¥' + price + '/人'
}
</script>

<template>
  <div class="shop-card" @click="openDetail">
    <div class="shop-card-header">
      <span class="shop-name">{{ shop.name || shop.sub_type || '店铺' }}</span>
      <span class="shop-score">{{ formatScore(shop.score) }}</span>
    </div>
    <div class="shop-card-meta">
      <span v-if="shop.avg_price">{{ formatPrice(shop.avg_price) }}</span>
      <span v-if="shop.area">{{ shop.area }}</span>
      <span v-if="shop.type">{{ shop.type }}</span>
    </div>
    <div v-if="shop.tags" class="shop-card-tags">
      <el-tag
        v-for="tag in parseTags(shop.tags)"
        :key="tag"
        size="small"
        type="info"
      >
        {{ tag }}
      </el-tag>
    </div>
    <div v-if="shop.open_hours" class="shop-card-hours">
      🕐 {{ shop.open_hours }}
    </div>

    <!-- 详情弹窗 -->
    <el-dialog
      v-model="showDetail"
      :title="shopDetail?.name || '店铺详情'"
      width="90%"
      :close-on-click-modal="true"
    >
      <div v-if="loading" v-loading="loading" style="min-height: 200px"></div>
      <div v-else-if="shopDetail" class="shop-detail">
        <p><strong>评分：</strong>{{ formatScore(shopDetail.score) }}</p>
        <p><strong>人均：</strong>{{ formatPrice(shopDetail.avgPrice || shopDetail.avg_price) }}</p>
        <p><strong>地址：</strong>{{ shopDetail.address }}</p>
        <p><strong>营业时间：</strong>{{ shopDetail.openHours || shopDetail.open_hours || '暂无' }}</p>
        <p v-if="shopDetail.description"><strong>简介：</strong>{{ shopDetail.description }}</p>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.shop-card {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  padding: 12px 14px;
  cursor: pointer;
  transition: box-shadow 0.2s;
}
.shop-card:hover {
  box-shadow: 0 2px 12px rgba(0,0,0,0.08);
}
.shop-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.shop-name {
  font-weight: 600;
  font-size: 16px;
  color: #303133;
}
.shop-score {
  color: #e6a23c;
  font-weight: 600;
}
.shop-card-meta {
  display: flex;
  gap: 10px;
  margin-top: 6px;
  font-size: 13px;
  color: #909399;
}
.shop-card-tags {
  margin-top: 8px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.shop-card-hours {
  margin-top: 6px;
  font-size: 12px;
  color: #c0c4cc;
}
</style>
