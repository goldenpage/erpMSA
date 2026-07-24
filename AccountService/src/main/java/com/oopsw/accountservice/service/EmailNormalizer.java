package com.oopsw.accountservice.service;

import java.util.Locale;
import org.springframework.stereotype.Component;

@Component
public class EmailNormalizer {

    public String normalize(String email) {
        if (email == null) {
            return null;
        }

        return email
            .trim()
            .toLowerCase(Locale.ROOT);
    }
}