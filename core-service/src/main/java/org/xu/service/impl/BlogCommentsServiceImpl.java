package org.xu.service.impl;

import org.xu.entity.BlogComments;
import org.xu.mapper.BlogCommentsMapper;
import org.xu.service.IBlogCommentsService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import org.springframework.stereotype.Service;

/**
 
 * @description: 博客评论接口实现

 **/
@Service
public class BlogCommentsServiceImpl extends ServiceImpl<BlogCommentsMapper, BlogComments> implements IBlogCommentsService {

}
