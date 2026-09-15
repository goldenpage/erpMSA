package com.oopsw.foundation;

import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** An explicit incomplete contract; never return fake business data or successful writes. */
@RestController
public class PendingDomainController {
    private final String service;
    public PendingDomainController(@Value("${spring.application.name}") String service) { this.service = service; }

    @RequestMapping({"${app.service.base-path}", "${app.service.base-path}/**"})
    public ResponseEntity<Map<String, Object>> pending(HttpServletRequest request) {
        return ResponseEntity.status(501).body(Map.of(
            "timestamp", Instant.now().toString(), "status", 501, "code", "ENDPOINT_NOT_IMPLEMENTED",
            "message", "아직 지원하지 않는 기능입니다.", "service", service,
            "path", request.getRequestURI(), "fieldErrors", List.of()));
    }
}
