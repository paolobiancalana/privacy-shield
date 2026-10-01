package pro.privacyshield;

import java.time.Duration;

/**
 * Configuration for the Privacy Shield client.
 * Use the builder to create an instance.
 */
public class PrivacyShieldConfig {
    private final String apiKey;
    private final String baseUrl;
    private final Duration timeout;
    private final String clientCert;
    private final String clientKey;
    private final String caCert;

    private PrivacyShieldConfig(Builder builder) {
        this.apiKey = builder.apiKey;
        this.baseUrl = builder.baseUrl;
        this.timeout = builder.timeout;
        this.clientCert = builder.clientCert;
        this.clientKey = builder.clientKey;
        this.caCert = builder.caCert;
    }

    public static Builder builder() {
        return new Builder();
    }

    public String getApiKey() { return apiKey; }
    public String getBaseUrl() { return baseUrl; }
    public Duration getTimeout() { return timeout; }
    public String getClientCert() { return clientCert; }
    public String getClientKey() { return clientKey; }
    public String getCaCert() { return caCert; }

    public static class Builder {
        private String apiKey;
        private String baseUrl = "https://api.privacyshield.pro";
        private Duration timeout = Duration.ofSeconds(5);
        private String clientCert;
        private String clientKey;
        private String caCert;

        public Builder apiKey(String apiKey) {
            this.apiKey = apiKey;
            return this;
        }

        public Builder baseUrl(String baseUrl) {
            this.baseUrl = baseUrl.replaceAll("/$", "");
            return this;
        }

        public Builder timeout(Duration timeout) {
            this.timeout = timeout;
            return this;
        }

        public Builder mTLS(String clientCert, String clientKey) {
            this.clientCert = clientCert;
            this.clientKey = clientKey;
            return this;
        }

        public Builder caCert(String caCert) {
            this.caCert = caCert;
            return this;
        }

        public PrivacyShieldConfig build() {
            if (apiKey == null || apiKey.isEmpty()) {
                throw new IllegalStateException("PrivacyShield: apiKey is required");
            }
            return new PrivacyShieldConfig(this);
        }
    }
}
