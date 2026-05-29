package org.xu.service;

import org.xu.dto.Result;
import org.xu.entity.Follow;
import com.baomidou.mybatisplus.extension.service.IService;

/**
 
 * @description: 关注接口

 **/
public interface IFollowService extends IService<Follow> {

    Result follow(Long followUserId, Boolean isFollow);

    Result isFollow(Long followUserId);

    Result followCommons(Long id);
}
