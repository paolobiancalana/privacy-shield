# Privacy Shield Java SDK

Official Java client for the [Privacy Shield](https://api.privacyshield.pro) PII tokenization platform.

## Features

- **PII Tokenization**: Detect and replace Italian PII with opaque tokens.
- **Rehydration**: Restore original values from tokens.
- **Vault Management**: Flush data when no longer needed.
- **mTLS Support**: Built-in support for client certificates (PEM).
- **Async API**: CompletableFuture support for non-blocking I/O.
- **Zero Dependencies**: Core client uses native `java.net.http.HttpClient` (Java 11+). Requires `Jackson` for JSON.

## Installation

Add the following to your `pom.xml`:

```xml
<dependency>
    <groupId>pro.privacyshield</groupId>
    <artifactId>privacy-shield-java</artifactId>
    <version>1.0.0</version>
</dependency>
```

## Basic Usage

```java
import pro.privacyshield.PrivacyShield;
import pro.privacyshield.PrivacyShieldConfig;
import pro.privacyshield.models.*;

import java.util.Arrays;

public class Main {
    public static void main(String[] args) {
        // 1. Configure the client
        PrivacyShieldConfig config = PrivacyShieldConfig.builder()
                .apiKey("ps_live_your_key")
                .build();

        PrivacyShield ps = new PrivacyShield(config);

        // 2. Tokenize text
        TokenizeRequest request = new TokenizeRequest();
        request.setTexts(Arrays.asList("Il Sig. Mario Rossi vive a Milano."));
        request.setOrganizationId("your-org-id");
        request.setRequestId("session-123");

        TokenizeResponse response = ps.tokenize(request);

        System.out.println("Tokenized: " + response.getTokenizedTexts().get(0));
        // Output: "Il Sig. [#pe:abc12345] vive a [#loc:xyz78901]."
    }
}
```

## mTLS Configuration

For enhanced security, you can provide client certificates:

```java
PrivacyShieldConfig config = PrivacyShieldConfig.builder()
        .apiKey("ps_live_your_key")
        .mTLS(clientCertPem, clientKeyPem)
        .caCert(caCertPem) // Optional
        .build();
```

## Error Handling

The SDK throws `PrivacyShieldApiException` for API errors (4xx/5xx).

```java
try {
    ps.tokenize(request);
} catch (PrivacyShieldApiException e) {
    System.err.println("API Error: " + e.getCode() + " - " + e.getMessage());
} catch (PrivacyShieldException e) {
    System.err.println("Network error: " + e.getMessage());
}
```

## Requirements

- Java 11 or higher.
- Jackson Databind 2.15+.
