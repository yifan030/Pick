package org.xu.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.extern.slf4j.Slf4j;
import org.xu.entity.UserPhone;
import org.xu.mapper.UserPhoneMapper;
import org.xu.service.IUserPhoneService;
import org.springframework.stereotype.Service;

/**
 
 * @description: 用户手机 接口实现

 **/
@Slf4j
@Service
public class UserPhoneServiceImpl extends ServiceImpl<UserPhoneMapper, UserPhone> implements IUserPhoneService {
    
}
