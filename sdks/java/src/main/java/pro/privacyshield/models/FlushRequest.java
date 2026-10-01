package pro.privacyshield.models;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Request to delete vault entries for a specific request.
 */
public class FlushRequest {
    @JsonProperty("organization_id")
    private String organizationId;
    
    @JsonProperty("request_id")
    private String requestId;

    public FlushRequest() {}

    public FlushRequest(String organizationId, String requestId) {
        this.organizationId = organizationId;
        this.requestId = requestId;
    }

    public String getOrganizationId() { return organizationId; }
    public void setOrganizationId(String organizationId) { this.organizationId = organizationId; }

    public String getRequestId() { return requestId; }
    public void setRequestId(String requestId) { this.requestId = requestId; }

    /**
     * Response from a flush request.
     */
    public static class Response {
        @JsonProperty("flushed_count")
        private int flushedCount;

        public Response() {}

        public int getFlushedCount() { return flushedCount; }
        public void setFlushedCount(int flushedCount) { this.flushedCount = flushedCount; }
    }
}
