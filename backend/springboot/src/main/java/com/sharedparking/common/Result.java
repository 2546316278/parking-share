package com.sharedparking.common;

import lombok.Data;

/**
 * 统一响应格式。
 *
 * 所有接口都返回 {code, message, data} 三段，前端只需判断 code == 0。
 * 不要有的接口返回裸数组、有的返回对象，前端会写得很难受。
 *
 * code 约定：
 *   0    成功
 *   1001 参数错误
 *   1002 资源不存在
 *   1003 状态冲突（如车位已被预约）
 *   5000 服务端异常
 */
@Data
public class Result<T> {

    private int code;
    private String message;
    private T data;

    private Result(int code, String message, T data) {
        this.code = code;
        this.message = message;
        this.data = data;
    }

    public static <T> Result<T> ok(T data) {
        return new Result<>(0, "ok", data);
    }

    public static <T> Result<T> ok() {
        return new Result<>(0, "ok", null);
    }

    public static <T> Result<T> fail(int code, String message) {
        return new Result<>(code, message, null);
    }
}
