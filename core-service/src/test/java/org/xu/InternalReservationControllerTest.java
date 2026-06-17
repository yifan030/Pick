package org.xu;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.xu.controller.InternalReservationController;
import org.xu.entity.Reservation;
import org.xu.service.IReservationService;

import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class InternalReservationControllerTest {

    MockMvc mockMvc;

    @Mock
    IReservationService reservationService;

    @InjectMocks
    InternalReservationController controller;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
        mockMvc = MockMvcBuilders.standaloneSetup(controller).build();
    }

    @Test
    void testQueueReservation() throws Exception {
        Reservation r = new Reservation();
        r.setId(1L);
        r.setType(0);
        r.setQueueNumber(3);
        r.setGuests(2);
        r.setStatus(0);
        when(reservationService.createReservation(any(Map.class))).thenReturn(r);

        mockMvc.perform(post("/api/reservations/internal")
                        .contentType("application/json")
                        .content("{\"userId\":100,\"shopId\":200,\"type\":0,\"guests\":2}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.queue_number").value(3))
                .andExpect(jsonPath("$.data.type").value(0));
    }

    @Test
    void testMakeReservation() throws Exception {
        Reservation r = new Reservation();
        r.setId(2L);
        r.setType(1);
        r.setGuests(4);
        r.setStatus(0);
        when(reservationService.createReservation(any(Map.class))).thenReturn(r);

        mockMvc.perform(post("/api/reservations/internal")
                        .contentType("application/json")
                        .content("{\"userId\":100,\"shopId\":200,\"type\":1,\"guests\":4,\"reserveTime\":\"2026-06-17T19:00:00\",\"phone\":\"13800000000\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.type").value(1));
    }

    @Test
    void testMissingUserIdReturnsFail() throws Exception {
        when(reservationService.createReservation(any(Map.class)))
                .thenThrow(new IllegalArgumentException("userId and shopId are required"));

        mockMvc.perform(post("/api/reservations/internal")
                        .contentType("application/json")
                        .content("{\"shopId\":200,\"type\":0,\"guests\":2}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(false));
    }
}
