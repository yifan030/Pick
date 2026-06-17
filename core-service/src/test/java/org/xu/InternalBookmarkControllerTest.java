package org.xu;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.xu.controller.InternalBookmarkController;
import org.xu.entity.Bookmark;
import org.xu.service.IBookmarkService;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class InternalBookmarkControllerTest {

    MockMvc mockMvc;

    @Mock
    IBookmarkService bookmarkService;

    @InjectMocks
    InternalBookmarkController controller;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
        mockMvc = MockMvcBuilders.standaloneSetup(controller).build();
    }

    @Test
    void testBookmarkShop() throws Exception {
        Bookmark bm = new Bookmark();
        bm.setId(1L);
        bm.setUserId(100L);
        bm.setShopId(200L);
        when(bookmarkService.bookmarkShop(100L, 200L)).thenReturn(bm);

        mockMvc.perform(post("/api/bookmarks/internal")
                        .contentType("application/json")
                        .content("{\"user_id\":100,\"shop_id\":200}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.bookmark_id").value(1));

        verify(bookmarkService).bookmarkShop(100L, 200L);
    }

    @Test
    void testListBookmarks() throws Exception {
        when(bookmarkService.listBookmarks(100L)).thenReturn(List.of(
                Map.of("bookmark_id", 1L, "shop_id", 200L, "shop_name", "测试店铺")
        ));

        mockMvc.perform(get("/api/bookmarks/internal/100"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data[0].shop_name").value("测试店铺"));
    }

    @Test
    void testRemoveBookmark() throws Exception {
        mockMvc.perform(delete("/api/bookmarks/internal/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(bookmarkService).removeBookmark(1L);
    }
}
