package pro.privacyshield.models;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * A single detected/tokenized PII entity.
 */
public class TokenEntry {
    @JsonProperty("token")
    private String token;
    
    @JsonProperty("original")
    private String original;
    
    @JsonProperty("type")
    private PiiType type;
    
    @JsonProperty("start")
    private int start;
    
    @JsonProperty("end")
    private int end;
    
    @JsonProperty("source")
    private DetectionSource source;

    // Default constructor for Jackson
    public TokenEntry() {}

    public TokenEntry(String token, String original, PiiType type, int start, int end, DetectionSource source) {
        this.token = token;
        this.original = original;
        this.type = type;
        this.start = start;
        this.end = end;
        this.source = source;
    }

    // Getters and Setters
    public String getToken() { return token; }
    public void setToken(String token) { this.token = token; }

    public String getOriginal() { return original; }
    public void setOriginal(String original) { this.original = original; }

    public PiiType getType() { return type; }
    public void setType(PiiType type) { this.type = type; }

    public int getStart() { return start; }
    public void setStart(int start) { this.start = start; }

    public int getEnd() { return end; }
    public void setEnd(int end) { this.end = end; }

    public DetectionSource getSource() { return source; }
    public void setSource(DetectionSource source) { this.source = source; }
}
