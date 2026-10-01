package pro.privacyshield.models;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Result of a flush request.
 */
public class FlushResponse {
    @JsonProperty("flushed_count")
    private int flushedCount;

    public FlushResponse() {}

    public FlushResponse(int flushedCount) {
        this.flushedCount = flushedCount;
    }

    public int getFlushedCount() { return flushedCount; }
    public void setFlushedCount(int flushedCount) { this.flushedCount = flushedCount; }
}
