package org.xu.sync;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.xu.dto.Result;
import org.xu.dto.ShopSyncDTO;
import org.xu.mapper.ShopMapper;

import java.util.List;

@RestController
@RequestMapping("/api/sync")
public class SyncController {

    private final ShopMapper shopMapper;

    public SyncController(ShopMapper shopMapper) {
        this.shopMapper = shopMapper;
    }

    @GetMapping("/shops")
    public Result<List<ShopSyncDTO>> syncShops(@RequestParam(name = "since", defaultValue = "0") Long since) {
        List<ShopSyncDTO> shops = shopMapper.selectSyncShops(since);
        return Result.ok(shops);
    }
}
