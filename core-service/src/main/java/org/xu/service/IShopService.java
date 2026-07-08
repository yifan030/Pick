package org.xu.service;

import org.xu.dto.Result;
import org.xu.dto.SaveShopDTO;
import org.xu.dto.UpdateShopDTO;
import org.xu.entity.Shop;
import com.baomidou.mybatisplus.extension.service.IService;

/**

 * @description: 商铺 接口

 **/
public interface IShopService extends IService<Shop> {

    Result<Long> saveShop(SaveShopDTO dto);

    Result queryById(Long id);

    Result updateShop(UpdateShopDTO dto);

    Result queryShopByType(Integer typeId, Integer current, Double longitude, Double latitude);
}
