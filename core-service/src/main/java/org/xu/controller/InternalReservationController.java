package org.xu.controller;

import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.xu.dto.Result;
import org.xu.entity.Reservation;
import org.xu.service.IReservationService;

import java.util.Map;

@RestController
@RequestMapping("/api/reservations")
public class InternalReservationController {

    @Resource
    private IReservationService reservationService;

    @PostMapping("/internal")
    public Result<Map<String, Object>> createReservation(@RequestBody Map<String, Object> body) {
        try {
            Reservation reservation = reservationService.createReservation(body);
            return Result.ok(Map.of(
                    "reservation_id", reservation.getId(),
                    "type", reservation.getType(),
                    "queue_number", reservation.getQueueNumber(),
                    "guests", reservation.getGuests(),
                    "status", reservation.getStatus(),
                    "message", reservation.getType() == 0
                            ? "排队取号成功"
                            : "预约已提交，等待确认"
            ));
        } catch (IllegalArgumentException e) {
            return Result.fail(e.getMessage());
        }
    }
}
