package org.xu.sync;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.xu.dto.BlogSyncDTO;
import org.xu.entity.User;
import org.xu.mapper.BlogMapper;
import org.xu.mapper.ShopMapper;
import org.xu.service.IUserService;

import java.time.LocalDateTime;
import java.util.List;

import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class BlogSyncControllerTest {

    private static final String VALID_TOKEN = "test-token";
    private BlogMapper blogMapper;
    private IUserService userService;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        blogMapper = mock(BlogMapper.class);
        userService = mock(IUserService.class);
        ShopMapper shopMapper = mock(ShopMapper.class);
        var controller = new SyncController(shopMapper, blogMapper, userService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .addInterceptors(new InternalTokenInterceptor(VALID_TOKEN))
                .build();
    }

    @Test
    void shouldReturn401WhenTokenMissing() throws Exception {
        mockMvc.perform(get("/api/sync/blogs").param("since", "0"))
                .andExpect(status().is(401));
    }

    @Test
    void shouldReturnAllBlogsWhenSinceIsZero() throws Exception {
        var dto = sampleBlogSyncDTO();
        when(blogMapper.selectSyncBlogs(0L)).thenReturn(List.of(dto));
        when(userService.getById(dto.getUserId())).thenReturn(sampleUser());

        mockMvc.perform(get("/api/sync/blogs")
                        .param("since", "0")
                        .header("X-Internal-Token", VALID_TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data[0].blogId").value(4))
                .andExpect(jsonPath("$.data[0].shopId").value(10))
                .andExpect(jsonPath("$.data[0].userNickname").value("测试用户"))
                .andExpect(jsonPath("$.data[0].title").value("探店标题"))
                .andExpect(jsonPath("$.data[0].content").value("探店正文"))
                .andExpect(jsonPath("$.data[0].updateTime").isNotEmpty());
    }

    @Test
    void shouldPassSinceParameterToMapper() throws Exception {
        long since = 1717200000000L;
        when(blogMapper.selectSyncBlogs(since)).thenReturn(List.of());

        mockMvc.perform(get("/api/sync/blogs")
                        .param("since", String.valueOf(since))
                        .header("X-Internal-Token", VALID_TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data").isEmpty());

        verify(blogMapper).selectSyncBlogs(since);
    }

    private BlogSyncDTO sampleBlogSyncDTO() {
        var dto = new BlogSyncDTO();
        dto.setBlogId(4L);
        dto.setShopId(10L);
        dto.setUserId(1987041610793484289L);
        dto.setTitle("探店标题");
        dto.setContent("探店正文");
        dto.setUpdateTime(LocalDateTime.of(2025, 11, 8, 6, 28, 37));
        return dto;
    }

    private User sampleUser() {
        var user = new User();
        user.setId(1987041610793484289L);
        user.setNickName("测试用户");
        return user;
    }
}
