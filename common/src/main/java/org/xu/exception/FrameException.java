package org.xu.exception;


import lombok.Data;
import lombok.EqualsAndHashCode;
import org.xu.enums.BaseCode;

/**
 
 * @description: 业务异常

 **/
@EqualsAndHashCode(callSuper = true)
@Data
public class FrameException extends BaseException {
	
	private Integer code;
	
	private String message;

	public FrameException() {
		super();
	}

	public FrameException(String message) {
		super(message);
	}
	
	public FrameException(Integer code, String message) {
		super(message);
		this.code = code;
		this.message = message;
	}
	
	public FrameException(BaseCode baseCode) {
		super(baseCode.getMsg());
		this.code = baseCode.getCode();
		this.message = baseCode.getMsg();
	}

	public FrameException(Throwable cause) {
		super(cause);
	}

	public FrameException(String message, Throwable cause) {
		super(message, cause);
		this.message = message;
	}
}
