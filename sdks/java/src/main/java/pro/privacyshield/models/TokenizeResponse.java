package pro.privacyshield.models;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

/**
 * Result of a tokenization request.
 */
public class TokenizeResponse {
    @JsonProperty("tokenized_texts")
    private List<String> tokenizedTexts;
    
    @JsonProperty("tokens")
    private List<TokenEntry> tokens;
    
    @JsonProperty("detection_ms")
    private double detectionMs;
    
    @JsonProperty("tokenization_ms")
    private double tokenizationMs;

    public TokenizeResponse() {}

    public TokenizeResponse(List<String> tokenizedTexts, List<TokenEntry> tokens, double detectionMs, double tokenizationMs) {
        this.tokenizedTexts = tokenizedTexts;
        this.tokens = tokens;
        this.detectionMs = detectionMs;
        this.tokenizationMs = tokenizationMs;
    }

    // Getters and Setters
    public List<String> getTokenizedTexts() { return tokenizedTexts; }
    public void setTokenizedTexts(List<String> tokenizedTexts) { this.tokenizedTexts = tokenizedTexts; }

    public List<TokenEntry> getTokens() { return tokens; }
    public void setTokens(List<TokenEntry> tokens) { this.tokens = tokens; }

    public double getDetectionMs() { return detectionMs; }
    public void setDetectionMs(double detectionMs) { this.detectionMs = detectionMs; }

    public double getTokenizationMs() { return tokenizationMs; }
    public void setTokenizationMs(double tokenizationMs) { this.tokenizationMs = tokenizationMs; }
}
