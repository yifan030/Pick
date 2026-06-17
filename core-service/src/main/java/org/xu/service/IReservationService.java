package org.xu.service;

import com.baomidou.mybatisplus.extension.service.IService;
import org.xu.entity.Reservation;

import java.util.Map;

public interface IReservationService extends IService<Reservation> {

    /**
     * 创建排队取号或电话预约
     * @param params {userId, shopId, type, guests, reserveTime?, phone?}
     * @return 创建成功的 Reservation
     */
    Reservation createReservation(Map<String, Object> params);
}
