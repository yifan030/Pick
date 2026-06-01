package org.xu.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Select;
import org.xu.dto.BlogSyncDTO;
import org.xu.entity.Blog;

import java.util.List;

public interface BlogMapper extends BaseMapper<Blog> {

    @Select("<script>"
            + "SELECT b.id AS blogId, b.shop_id AS shopId, b.user_id AS userId,"
            + " b.title, b.content, b.update_time AS updateTime "
            + "FROM tb_blog b "
            + "<if test='since != null and since > 0'>"
            + "WHERE b.update_time &gt;= TO_TIMESTAMP(#{since}/1000.0)"
            + "</if>"
            + "ORDER BY b.id"
            + "</script>")
    List<BlogSyncDTO> selectSyncBlogs(Long since);
}
