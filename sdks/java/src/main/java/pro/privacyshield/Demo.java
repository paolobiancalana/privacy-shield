package pro.privacyshield;

import pro.privacyshield.models.*;
import java.util.Collections;

public class Demo {
    public static void main(String[] args) {
        String apiKey = System.getenv("PS_API_KEY");
        String baseUrl = System.getenv("PS_BASE_URL");

        if (apiKey == null || apiKey.isEmpty()) {
            System.err.println("Error: PS_API_KEY environment variable is not set.");
            System.exit(1);
        }

        if (baseUrl == null || baseUrl.isEmpty()) {
            baseUrl = "http://host.docker.internal:8000";
        }

        System.out.println("--- Privacy Shield Java SDK Sandbox ---");
        System.out.println("Connecting to: " + baseUrl);

        try {
            // 1. Initialize Client
            PrivacyShieldConfig config = PrivacyShieldConfig.builder()
                    .apiKey(apiKey)
                    .baseUrl(baseUrl)
                    .build();

            PrivacyShield ps = new PrivacyShield(config);

            // 2. Health Check
            HealthResponse health = ps.health();
            System.out.println("API Health Status: " + health.getStatus());

            // 3. Tokenize Demo
            String originalText = "Il Sig. Mario Rossi risiede in Via Roma 1, Milano.";
            System.out.println("\nOriginal Text: " + originalText);

            TokenizeRequest request = new TokenizeRequest();
            request.setTexts(Collections.singletonList(originalText));
            request.setOrganizationId("5037cf1d-ce2d-42b0-96b8-f9ae4a0f9f25");
            request.setRequestId(java.util.UUID.randomUUID().toString());

            TokenizeResponse tokenizeResponse = ps.tokenize(request);
            String tokenizedText = tokenizeResponse.getTokenizedTexts().get(0);
            System.out.println("Tokenized Text: " + tokenizedText);

            // 4. Rehydrate Demo
            if (tokenizeResponse.getTokens() != null && !tokenizeResponse.getTokens().isEmpty()) {
                System.out.println("\nRehydrating tokens...");
                RehydrateRequest rehydrateRequest = new RehydrateRequest();
                rehydrateRequest.setText(tokenizedText);
                rehydrateRequest.setOrganizationId("5037cf1d-ce2d-42b0-96b8-f9ae4a0f9f25");
                rehydrateRequest.setRequestId(request.getRequestId());
                
                RehydrateResponse rehydrateResponse = ps.rehydrate(rehydrateRequest);
                System.out.println("Rehydrated Result: " + rehydrateResponse.getText());
                System.out.println("Rehydrated Count: " + rehydrateResponse.getRehydratedCount());
            }

            System.out.println("\n--- Sandbox Test Completed Successfully ---");

        } catch (Exception e) {
            System.err.println("\n--- Sandbox Test Failed ---");
            e.printStackTrace();
            System.exit(1);
        }
    }
}
