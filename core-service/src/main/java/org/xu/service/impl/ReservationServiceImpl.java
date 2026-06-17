package org.xu.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import jakarta.annotation.Resource;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.xu.entity.Reservation;
import org.xu.mapper.ReservationMapper;
import org.xu.service.IReservationService;
import org.xu.toolkit.SnowflakeIdGenerator;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Map;

@Service
public class ReservationServiceImpl
        extends ServiceImpl<ReservationMapper, Reservation>
        implements IReservationService {

    @Resource
    private SnowflakeIdGenerator snowflakeIdGenerator;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public Reservation createReservation(Map<String, Object> params) {
        Long userId = params.get("userId") instanceof Number n ? n.longValue() : null;
        Long shopId = params.get("shopId") instanceof Number n ? n.longValue() : null;
        Integer type = params.get("type") instanceof Number n ? n.intValue() : 0;
        Integer guests = params.get("guests") instanceof Number n ? n.intValue() : 1;

        if (userId == null || shopId == null) {
            throw new IllegalArgumentException("userId and shopId are required");
        }

        Reservation reservation = new Reservation();
        reservation.setId(snowflakeIdGenerator.nextId());
        reservation.setUserId(userId);
        reservation.setShopId(shopId);
        reservation.setType(type);
        reservation.setGuests(guests);
        reservation.setStatus(0); // 待确认

        if (params.get("reserveTime") instanceof String timeStr && !timeStr.isBlank()) {
            reservation.setReserveTime(LocalDateTime.parse(timeStr, DateTimeFormatter.ISO_LOCAL_DATE_TIME));
        }
        if (params.get("phone") instanceof String phone) {
            reservation.setContactPhone(phone);
        }
        if (params.get("remark") instanceof String remark) {
            reservation.setRemark(remark);
        }

        // 排队取号：根据店铺当前排队数自动分配号
        if (type == 0) {
            long queueCount = lambdaQuery()
                    .eq(Reservation::getShopId, shopId)
                    .eq(Reservation::getType, 0)
                    .eq(Reservation::getStatus, 0)
                    .count();
            reservation.setQueueNumber((int) (queueCount + 1));
        }

        reservation.setCreateTime(LocalDateTime.now());
        reservation.setUpdateTime(LocalDateTime.now());
        save(reservation);

        return reservation;
    }
}
