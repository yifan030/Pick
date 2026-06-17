package org.xu;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.xu.controller.InternalOrderController;
import org.xu.service.IVoucherOrderService;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class InternalOrderControllerTest {

    MockMvc mockMvc;

    @Mock
    IVoucherOrderService voucherOrderService;

    @InjectMocks
    InternalOrderController controller;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
        mockMvc = MockMvcBuilders.standaloneSetup(controller).build();
    }

    @Test
    void testCheckOrderStatus() throws Exception {
        when(voucherOrderService.getOrderStatus(1L)).thenReturn(Map.of(
                "order_id", 1L, "status", 0, "status_text", "正常"
        ));

        mockMvc.perform(get("/api/orders/internal/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.status").value(0));

        verify(voucherOrderService).getOrderStatus(1L);
    }

    @Test
    void testListUserOrders() throws Exception {
        when(voucherOrderService.listUserOrders(eq(100L), any()))
                .thenReturn(List.of(Map.of("order_id", 1L, "status", 0)));

        mockMvc.perform(get("/api/orders/internal/user/100").param("status", "NORMAL"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data[0].order_id").value(1));

        verify(voucherOrderService).listUserOrders(100L, "NORMAL");
    }

    @Test
    void testRequestRefund() throws Exception {
        when(voucherOrderService.requestRefund(1L, "不想要了")).thenReturn(1L);

        mockMvc.perform(post("/api/orders/internal/1/refund")
                        .contentType("application/json")
                        .content("{\"reason\":\"不想要了\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.order_id").value(1));

        verify(voucherOrderService).requestRefund(1L, "不想要了");
    }
}
