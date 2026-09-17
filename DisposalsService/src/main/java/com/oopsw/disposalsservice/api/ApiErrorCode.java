package com.oopsw.disposalsservice.api;
import org.springframework.http.HttpStatus;
public enum ApiErrorCode {
    INVALID_REQUEST(HttpStatus.BAD_REQUEST, "요청 값이 올바르지 않습니다."),
    MALFORMED_REQUEST(HttpStatus.BAD_REQUEST, "요청 본문을 읽을 수 없습니다."),
    CONCURRENT_MODIFICATION(HttpStatus.CONFLICT, "다른 요청과 충돌했습니다. 다시 조회해 주세요."),
    RESOURCE_NOT_FOUND(HttpStatus.NOT_FOUND, "요청한 리소스를 찾을 수 없습니다."),
    METHOD_NOT_ALLOWED(HttpStatus.METHOD_NOT_ALLOWED, "지원하지 않는 HTTP 메서드입니다."),
    INTERNAL_SERVER_ERROR(HttpStatus.INTERNAL_SERVER_ERROR, "서버 내부 오류가 발생했습니다."),
    DISPOSAL_NOT_FOUND(HttpStatus.NOT_FOUND, "폐기 요청을 찾을 수 없습니다."),
    REQUEST_CONFLICT(HttpStatus.CONFLICT, "같은 요청 ID에 다른 폐기 내용이 전달되었습니다.");
    private final HttpStatus status;
    private final String message;
    ApiErrorCode(HttpStatus status, String message) { this.status=status; this.message=message; }
    public HttpStatus status() { return status; }
    public String message() { return message; }
}
