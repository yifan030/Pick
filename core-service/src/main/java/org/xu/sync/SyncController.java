package org.xu.sync;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.xu.dto.BlogSyncDTO;
import org.xu.dto.Result;
import org.xu.dto.ShopSyncDTO;
import org.xu.entity.User;
import org.xu.mapper.BlogMapper;
import org.xu.mapper.ShopMapper;
import org.xu.service.IUserService;

import java.util.List;

@RestController
@RequestMapping("/api/sync")
public class SyncController {

    private final ShopMapper shopMapper;
    private final BlogMapper blogMapper;
    private final IUserService userService;

    public SyncController(ShopMapper shopMapper, BlogMapper blogMapper, IUserService userService) {
        this.shopMapper = shopMapper;
        this.blogMapper = blogMapper;
        this.userService = userService;
    }

    @GetMapping("/shops")
    public Result<List<ShopSyncDTO>> syncShops(@RequestParam(name = "since", defaultValue = "0") Long since) {
        List<ShopSyncDTO> shops = shopMapper.selectSyncShops(since);
        return Result.ok(shops);
    }

    @GetMapping("/blogs")
    public Result<List<BlogSyncDTO>> syncBlogs(@RequestParam(name = "since", defaultValue = "0") Long since) {
        List<BlogSyncDTO> blogs = blogMapper.selectSyncBlogs(since);
        blogs.forEach(this::enrichUserNickname);
        return Result.ok(blogs);
    }

    private void enrichUserNickname(BlogSyncDTO blog) {
        if (blog.getUserId() == null) {
            blog.setUserNickname("");
            return;
        }
        User user = userService.getById(blog.getUserId());
        blog.setUserNickname(user != null && user.getNickName() != null ? user.getNickName() : "");
    }
}
