package org.xu.dto;

import lombok.Data;
import java.util.List;

@Data
public class VoucherAvailableRequestDTO {
    private List<Long> shopIds;
    private Long userId;
}
