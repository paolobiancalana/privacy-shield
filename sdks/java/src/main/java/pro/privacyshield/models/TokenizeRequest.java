package pro.privacyshield.models;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.Map;

/**
 * Request to tokenize one or more texts.
 */
public class TokenizeRequest {
    @JsonProperty("texts")
    private List<String> texts;
    
    @JsonProperty("organization_id")
    private String organizationId;
    
    @JsonProperty("request_id")
    private String requestId;
    
    @JsonProperty("existing_tokens")
    private Map<String, String> existingTokens;

    public TokenizeRequest() {}

    public TokenizeRequest(List<String> texts, String organizationId, String requestId, Map<String, String> existingTokens) {
        this.texts = texts;
        this.organizationId = organizationId;
        this.requestId = requestId;
        this.existingTokens = existingTokens;
    }

    // Getters and Setters
    public List<String> getTexts() { return texts; }
    public void setTexts(List<String> texts) { this.texts = texts; }

    public String getOrganizationId() { return organizationId; }
    public void setOrganizationId(String organizationId) { this.organizationId = organizationId; }

    public String getRequestId() { return requestId; }
    public void setRequestId(String requestId) { this.requestId = requestId; }

    public Map<String, String> getExistingTokens() { return existingTokens; }
    public void setExistingTokens(Map<String, String> existingTokens) { this.existingTokens = existingTokens; }
}
