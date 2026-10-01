package pro.privacyshield.models;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Result of a rehydration request.
 */
public class RehydrateResponse {
    @JsonProperty("text")
    private String text;
    
    @JsonProperty("rehydrated_count")
    private int rehydratedCount;

    public RehydrateResponse() {}

    public RehydrateResponse(String text, int rehydratedCount) {
        this.text = text;
        this.rehydratedCount = rehydratedCount;
    }

    public String getText() { return text; }
    public void setText(String text) { this.text = text; }

    public int getRehydratedCount() { return rehydratedCount; }
    public void setRehydratedCount(int rehydratedCount) { this.rehydratedCount = rehydratedCount; }
}
