package org.xu.service;

import com.baomidou.mybatisplus.extension.service.IService;
import org.xu.entity.Bookmark;

import java.util.List;
import java.util.Map;

public interface IBookmarkService extends IService<Bookmark> {

    /** 收藏店铺，返回创建的 Bookmark */
    Bookmark bookmarkShop(Long userId, Long shopId);

    /** 列出用户所有收藏，含店铺基本信息 */
    List<Map<String, Object>> listBookmarks(Long userId);

    /** 取消收藏 */
    void removeBookmark(Long bookmarkId);
}
