package org.xu.mapper;

import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.xu.dto.ShopImageDTO;
import org.xu.entity.ShopImage;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import java.util.List;

public interface ShopImageMapper extends BaseMapper<ShopImage> {

    @Select("<script>"
            + "SELECT i.id, i.shop_id AS shopId, i.url, i.type, i.alt, i.sort "
            + "FROM tb_shop_image i "
            + "WHERE i.shop_id IN "
            + "<foreach item='id' collection='shopIds' open='(' separator=',' close=')'>"
            + "#{id}"
            + "</foreach>"
            + "ORDER BY i.shop_id, i.sort"
            + "</script>")
    List<ShopImageDTO> selectShopImagesByShopIds(@Param("shopIds") List<Long> shopIds);
}
