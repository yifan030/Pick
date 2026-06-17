package org.xu.controller;

import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.xu.dto.Result;
import org.xu.entity.Bookmark;
import org.xu.service.IBookmarkService;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/bookmarks")
public class InternalBookmarkController {

    @Resource
    private IBookmarkService bookmarkService;

    @PostMapping("/internal")
    public Result<Map<String, Object>> bookmarkShop(@RequestBody Map<String, Object> body) {
        Long userId = body.get("user_id") instanceof Number n ? n.longValue() : null;
        Long shopId = body.get("shop_id") instanceof Number n ? n.longValue() : null;
        if (userId == null || shopId == null) {
            return Result.fail("user_id and shop_id are required");
        }
        Bookmark bookmark = bookmarkService.bookmarkShop(userId, shopId);
        return Result.ok(Map.of(
                "bookmark_id", bookmark.getId(),
                "shop_id", bookmark.getShopId(),
                "message", "收藏成功"
        ));
    }

    @GetMapping("/internal/{userId}")
    public Result<List<Map<String, Object>>> listBookmarks(@PathVariable("userId") Long userId) {
        List<Map<String, Object>> bookmarks = bookmarkService.listBookmarks(userId);
        return Result.ok(bookmarks);
    }

    @DeleteMapping("/internal/{bookmarkId}")
    public Result<Void> removeBookmark(@PathVariable("bookmarkId") Long bookmarkId) {
        bookmarkService.removeBookmark(bookmarkId);
        return Result.ok();
    }
}
