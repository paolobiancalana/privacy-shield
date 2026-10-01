package pro.privacyshield;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import pro.privacyshield.exceptions.PrivacyShieldApiException;
import pro.privacyshield.exceptions.PrivacyShieldException;
import pro.privacyshield.models.*;

import javax.net.ssl.SSLContext;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.concurrent.CompletableFuture;

/**
 * Privacy Shield client.
 *
 * Usage:
 * <pre>
 * PrivacyShieldConfig config = PrivacyShieldConfig.builder()
 *     .apiKey("ps_live_xxx")
 *     .build();
 * PrivacyShield client = new PrivacyShield(config);
 *
 * TokenizeResponse response = client.tokenize(new TokenizeRequest(...));
 * </pre>
 */
public class PrivacyShield {
    private final PrivacyShieldConfig config;
    private final HttpClient httpClient;
    private final ObjectMapper objectMapper;

    public PrivacyShield(PrivacyShieldConfig config) {
        this(config, createDefaultHttpClient(config));
    }

    public PrivacyShield(PrivacyShieldConfig config, HttpClient httpClient) {
        this.config = config;
        this.httpClient = httpClient;
        this.objectMapper = new ObjectMapper()
                .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false)
                .setSerializationInclusion(JsonInclude.Include.NON_NULL);
    }

    // --- Public API ---

    public TokenizeResponse tokenize(TokenizeRequest request) {
        return post("/api/v1/tokenize", request, TokenizeResponse.class);
    }

    public RehydrateResponse rehydrate(RehydrateRequest request) {
        return post("/api/v1/rehydrate", request, RehydrateResponse.class);
    }

    public FlushResponse flush(FlushRequest request) {
        return post("/api/v1/flush", request, FlushResponse.class);
    }

    public HealthResponse health() {
        return get("/health", HealthResponse.class);
    }

    // --- Async API ---

    public CompletableFuture<TokenizeResponse> tokenizeAsync(TokenizeRequest request) {
        return postAsync("/api/v1/tokenize", request, TokenizeResponse.class);
    }

    // --- Internals ---

    private <T> T post(String path, Object body, Class<T> responseClass) {
        try {
            String jsonBody = objectMapper.writeValueAsString(body);
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(config.getBaseUrl() + path))
                    .header("Content-Type", "application/json")
                    .header("X-Api-Key", config.getApiKey())
                    .timeout(config.getTimeout())
                    .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                    .build();

            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            return handleResponse(response, responseClass);
        } catch (IOException | InterruptedException e) {
            throw new PrivacyShieldException("Request failed: " + e.getMessage(), e);
        }
    }

    private <T> CompletableFuture<T> postAsync(String path, Object body, Class<T> responseClass) {
        try {
            String jsonBody = objectMapper.writeValueAsString(body);
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(config.getBaseUrl() + path))
                    .header("Content-Type", "application/json")
                    .header("X-Api-Key", config.getApiKey())
                    .timeout(config.getTimeout())
                    .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                    .build();

            return httpClient.sendAsync(request, HttpResponse.BodyHandlers.ofString())
                    .thenApply(response -> handleResponse(response, responseClass));
        } catch (JsonProcessingException e) {
            CompletableFuture<T> future = new CompletableFuture<>();
            future.completeExceptionally(new PrivacyShieldException("JSON serialization failed", e));
            return future;
        }
    }

    private <T> T get(String path, Class<T> responseClass) {
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(config.getBaseUrl() + path))
                    .header("X-Api-Key", config.getApiKey())
                    .timeout(config.getTimeout())
                    .GET()
                    .build();

            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            return handleResponse(response, responseClass);
        } catch (IOException | InterruptedException e) {
            throw new PrivacyShieldException("Request failed: " + e.getMessage(), e);
        }
    }

    private static HttpClient createDefaultHttpClient(PrivacyShieldConfig config) {
        HttpClient.Builder builder = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(config.getTimeout());

        if (config.getClientCert() != null && config.getClientKey() != null) {
            try {
                SSLContext sslContext = SSLContextHelper.createSSLContext(
                        config.getClientCert(),
                        config.getClientKey(),
                        config.getCaCert()
                );
                builder.sslContext(sslContext);
            } catch (Exception e) {
                throw new PrivacyShieldException("Failed to initialize mTLS: " + e.getMessage(), e);
            }
        }

        return builder.build();
    }

    private <T> T handleResponse(HttpResponse<String> response, Class<T> responseClass) {
        int status = response.statusCode();
        String body = response.body();

        if (status >= 200 && status < 300) {
            try {
                return objectMapper.readValue(body, responseClass);
            } catch (JsonProcessingException e) {
                throw new PrivacyShieldException("Failed to parse response JSON: " + body, e);
            }
        } else {
            try {
                PrivacyShieldError error = objectMapper.readValue(body, PrivacyShieldError.class);
                throw new PrivacyShieldApiException(status, error);
            } catch (JsonProcessingException e) {
                // Return the raw body in the exception for debugging
                throw new PrivacyShieldApiException(status, "HTTP Error " + status, "UNKNOWN", body);
            }
        }
    }
}
