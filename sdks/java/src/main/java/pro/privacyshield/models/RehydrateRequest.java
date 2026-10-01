package pro.privacyshield.models;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Request to restore original PII from tokens in a text.
 */
public class RehydrateRequest {
    @JsonProperty("text")
    private String text;
    
    @JsonProperty("organization_id")
    private String organizationId;
    
    @JsonProperty("request_id")
    private String requestId;

    public RehydrateRequest() {}

    public RehydrateRequest(String text, String organizationId, String requestId) {
        this.text = text;
        this.organizationId = organizationId;
        this.requestId = requestId;
    }

    public String getText() { return text; }
    public void setText(String text) { this.text = text; }

    public String getOrganizationId() { return organizationId; }
    public void setOrganizationId(String organizationId) { this.organizationId = organizationId; }

    public String getRequestId() { return requestId; }
    public void setRequestId(String requestId) { this.requestId = requestId; }
}
