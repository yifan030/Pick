package org.xu.service;

import org.xu.dto.Result;
import org.xu.entity.Shop;
import com.baomidou.mybatisplus.extension.service.IService;

/**
 
 * @description: 商铺 接口

 **/
public interface IShopService extends IService<Shop> {

    Result saveShop(Shop shop);
    
    Result queryById(Long id);

    Result update(Shop shop);

    Result queryShopByType(Integer typeId, Integer current, Double x, Double y);
}
