package org.xu.sync;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.xu.dto.ShopSyncDTO;
import org.xu.mapper.BlogMapper;
import org.xu.mapper.ShopMapper;
import org.xu.service.IUserService;

import java.time.LocalDateTime;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class SyncControllerTest {

    private static final String VALID_TOKEN = "test-token";
    private ShopMapper shopMapper;
    private BlogMapper blogMapper;
    private IUserService userService;
    private MockMvc mockMvc;
    private ObjectMapper objectMapper;

    @BeforeEach
    void setUp() {
        shopMapper = mock(ShopMapper.class);
        blogMapper = mock(BlogMapper.class);
        userService = mock(IUserService.class);
        var controller = new SyncController(shopMapper, blogMapper, userService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .addInterceptors(new InternalTokenInterceptor(VALID_TOKEN))
                .build();
        objectMapper = new ObjectMapper();
    }

    @Test
    void shouldReturn401WhenTokenMissing() throws Exception {
        mockMvc.perform(get("/api/sync/shops").param("since", "0"))
                .andExpect(status().is(401));
    }

    @Test
    void shouldReturn401WhenTokenWrong() throws Exception {
        mockMvc.perform(get("/api/sync/shops")
                        .param("since", "0")
                        .header("X-Internal-Token", "bad-token"))
                .andExpect(status().is(401));
    }

    @Test
    void shouldReturnAllShopsWhenSinceIsZero() throws Exception {
        var dto = sampleShopSyncDTO();
        when(shopMapper.selectSyncShops(0L)).thenReturn(List.of(dto));

        mockMvc.perform(get("/api/sync/shops")
                        .param("since", "0")
                        .header("X-Internal-Token", VALID_TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data[0].shopId").value(1))
                .andExpect(jsonPath("$.data[0].name").value("测试店铺"))
                .andExpect(jsonPath("$.data[0].type").value("美食"))
                .andExpect(jsonPath("$.data[0].subType").value("火锅"))
                .andExpect(jsonPath("$.data[0].area").value("陆家嘴"))
                .andExpect(jsonPath("$.data[0].address").value("世纪大道100号"))
                .andExpect(jsonPath("$.data[0].longitude").value(121.5))
                .andExpect(jsonPath("$.data[0].latitude").value(31.2))
                .andExpect(jsonPath("$.data[0].avgPrice").value(150))
                .andExpect(jsonPath("$.data[0].score").value(45))
                .andExpect(jsonPath("$.data[0].openHours").value("10:00-22:00"))
                .andExpect(jsonPath("$.data[0].images").value("img1.jpg,img2.jpg"))
                .andExpect(jsonPath("$.data[0].description").value("这是一家很棒的火锅店"))
                .andExpect(jsonPath("$.data[0].tags").value("[\"停车方便\",\"有包厢\"]"))
                .andExpect(jsonPath("$.data[0].recommendedScenes").value("[\"约会\",\"家庭聚餐\"]"))
                .andExpect(jsonPath("$.data[0].updateTime").isNotEmpty());
    }

    @Test
    void shouldPassSinceParameterToMapper() throws Exception {
        long since = 1717200000000L;
        when(shopMapper.selectSyncShops(since)).thenReturn(List.of());

        mockMvc.perform(get("/api/sync/shops")
                        .param("since", String.valueOf(since))
                        .header("X-Internal-Token", VALID_TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data").isEmpty());

        verify(shopMapper).selectSyncShops(since);
    }

    @Test
    void shouldDefaultSinceToZeroWhenMissing() throws Exception {
        when(shopMapper.selectSyncShops(0L)).thenReturn(List.of());

        mockMvc.perform(get("/api/sync/shops")
                        .header("X-Internal-Token", VALID_TOKEN))
                .andExpect(status().isOk());

        verify(shopMapper).selectSyncShops(0L);
    }

    private ShopSyncDTO sampleShopSyncDTO() {
        var dto = new ShopSyncDTO();
        dto.setShopId(1L);
        dto.setName("测试店铺");
        dto.setType("美食");
        dto.setSubType("火锅");
        dto.setArea("陆家嘴");
        dto.setAddress("世纪大道100号");
        dto.setLongitude(121.5);
        dto.setLatitude(31.2);
        dto.setAvgPrice(150L);
        dto.setScore(45);
        dto.setOpenHours("10:00-22:00");
        dto.setImages("img1.jpg,img2.jpg");
        dto.setDescription("这是一家很棒的火锅店");
        dto.setTags("[\"停车方便\",\"有包厢\"]");
        dto.setRecommendedScenes("[\"约会\",\"家庭聚餐\"]");
        dto.setUpdateTime(LocalDateTime.of(2024, 6, 1, 12, 0));
        return dto;
    }
}
