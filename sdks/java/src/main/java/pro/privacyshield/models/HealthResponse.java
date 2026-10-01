package pro.privacyshield.models;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Map;

/**
 * Health check status.
 */
public class HealthResponse {
    @JsonProperty("status")
    private String status;
    
    @JsonProperty("components")
    private Map<String, ComponentInfo> components;
    
    @JsonProperty("version")
    private String version;

    public HealthResponse() {}

    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }

    public Map<String, ComponentInfo> getComponents() { return components; }
    public void setComponents(Map<String, ComponentInfo> components) { this.components = components; }

    public String getVersion() { return version; }
    public void setVersion(String version) { this.version = version; }

    public static class ComponentInfo {
        @JsonProperty("status")
        private String status;
        
        @JsonProperty("latency_ms")
        private Double latencyMs;

        public String getStatus() { return status; }
        public void setStatus(String status) { this.status = status; }

        public Double getLatencyMs() { return latencyMs; }
        public void setLatencyMs(Double latencyMs) { this.latencyMs = latencyMs; }
    }
}
