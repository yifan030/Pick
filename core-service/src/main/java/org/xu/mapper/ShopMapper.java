package org.xu.mapper;

import org.apache.ibatis.annotations.Select;
import org.xu.dto.ShopSyncDTO;
import org.xu.entity.Shop;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import java.util.List;

public interface ShopMapper extends BaseMapper<Shop> {

    @Select("<script>"
            + "SELECT s.id AS shopId, s.name,"
            + " st_main.name AS type, st_sub.name AS subType,"
            + " s.area, s.address, s.longitude, s.latitude,"
            + " s.avg_price AS avgPrice, s.score,"
            + " s.open_hours AS openHours,"
            + " s.description, s.tags, s.recommended_scenes AS recommendedScenes,"
            + " s.update_time AS updateTime "
            + "FROM tb_shop s "
            + "LEFT JOIN tb_shop_type st_sub ON s.type_id = st_sub.id "
            + "LEFT JOIN tb_shop_type st_main ON st_sub.parent_id = st_main.id "
            + "<if test='since != null and since > 0'>"
            + "WHERE s.update_time >= FROM_UNIXTIME(#{since}/1000)"
            + "</if>"
            + "ORDER BY s.id"
            + "</script>")
    List<ShopSyncDTO> selectSyncShops(Long since);
}
