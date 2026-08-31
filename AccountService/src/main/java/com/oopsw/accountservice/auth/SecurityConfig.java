package com.oopsw.accountservice.auth;


import com.oopsw.accountservice.api.ApiErrorCode;
import com.oopsw.accountservice.api.ApiErrorWriter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

@Configuration
public class SecurityConfig {

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    public SecurityFilterChain securityFilterChain(
        HttpSecurity http,
        JwtProvider jwtProvider,
        ApiErrorWriter apiErrorWriter
    ) throws Exception {

        http
            .csrf(AbstractHttpConfigurer::disable)
            .sessionManagement(session ->
                session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(authorize -> authorize
                .requestMatchers(
                    "/account/auth/register",
                    "/account/auth/login",
                    "/account/auth/refresh",
                    "/account/auth/logout",
                    "/actuator/health",
                    "/actuator/prometheus",
                    "/error"
                ).permitAll()
                .requestMatchers("/account/manager/**").hasRole("MANAGER")
                .anyRequest().authenticated()
            )
            .exceptionHandling(ex -> ex
                .authenticationEntryPoint((req, res, e) ->
                    apiErrorWriter.write(
                        req,
                        res,
                        ApiErrorCode.AUTHENTICATION_REQUIRED
                    ))
                .accessDeniedHandler((req, res, e) ->
                    apiErrorWriter.write(
                        req,
                        res,
                        ApiErrorCode.ACCESS_DENIED
                    ))
            )
            .addFilterBefore(
                new JwtAuthorizationFilter(jwtProvider, apiErrorWriter),
                UsernamePasswordAuthenticationFilter.class
            );

        return http.build();
    }
}
