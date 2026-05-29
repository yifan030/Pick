package org.xu.service;

import com.baomidou.mybatisplus.extension.service.IService;
import org.xu.dto.LoginFormDTO;
import org.xu.dto.Result;
import org.xu.entity.User;
import jakarta.servlet.http.HttpSession;


/**
 
 * @description: 用户 接口

 **/
public interface IUserService extends IService<User> {

    Result<String> sendCode(String phone, HttpSession session);

    Result<String> login(LoginFormDTO loginForm, HttpSession session);

    Result<Void> sign();

    Result<Integer> signCount();

}
