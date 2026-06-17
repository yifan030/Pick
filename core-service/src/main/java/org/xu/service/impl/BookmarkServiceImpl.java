package org.xu.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import jakarta.annotation.Resource;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.xu.entity.Bookmark;
import org.xu.entity.Shop;
import org.xu.mapper.BookmarkMapper;
import org.xu.mapper.ShopMapper;
import org.xu.service.IBookmarkService;
import org.xu.toolkit.SnowflakeIdGenerator;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class BookmarkServiceImpl
        extends ServiceImpl<BookmarkMapper, Bookmark>
        implements IBookmarkService {

    @Resource
    private SnowflakeIdGenerator snowflakeIdGenerator;

    @Resource
    private ShopMapper shopMapper;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public Bookmark bookmarkShop(Long userId, Long shopId) {
        // 检查是否已收藏
        Bookmark existing = lambdaQuery()
                .eq(Bookmark::getUserId, userId)
                .eq(Bookmark::getShopId, shopId)
                .one();
        if (existing != null) {
            return existing;
        }
        Bookmark bookmark = new Bookmark();
        bookmark.setId(snowflakeIdGenerator.nextId());
        bookmark.setUserId(userId);
        bookmark.setShopId(shopId);
        bookmark.setCreateTime(LocalDateTime.now());
        save(bookmark);
        return bookmark;
    }

    @Override
    public List<Map<String, Object>> listBookmarks(Long userId) {
        List<Bookmark> bookmarks = lambdaQuery()
                .eq(Bookmark::getUserId, userId)
                .orderByDesc(Bookmark::getCreateTime)
                .list();
        List<Map<String, Object>> result = new ArrayList<>();
        for (Bookmark bm : bookmarks) {
            Map<String, Object> item = new HashMap<>();
            item.put("bookmark_id", bm.getId());
            item.put("shop_id", bm.getShopId());
            item.put("create_time", bm.getCreateTime().toString());
            Shop shop = shopMapper.selectById(bm.getShopId());
            if (shop != null) {
                item.put("shop_name", shop.getName());
                item.put("shop_type", shop.getTypeId());
                item.put("area", shop.getArea());
                item.put("avg_price", shop.getAvgPrice());
                item.put("score", shop.getScore());
            }
            result.add(item);
        }
        return result;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void removeBookmark(Long bookmarkId, Long userId) {
        Bookmark bm = getById(bookmarkId);
        if (bm == null || !bm.getUserId().equals(userId)) {
            throw new IllegalArgumentException("无权限操作该收藏");
        }
        removeById(bookmarkId);
    }
}
