package pro.privacyshield.models;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Standard error response from the Privacy Shield API.
 */
public class PrivacyShieldError {
    @JsonProperty("error")
    private String error;
    
    @JsonProperty("code")
    private String code;
    
    @JsonProperty("detail")
    private String detail;

    public PrivacyShieldError() {}

    public String getError() { return error; }
    public void setError(String error) { this.error = error; }

    public String getCode() { return code; }
    public void setCode(String code) { this.code = code; }

    public String getDetail() { return detail; }
    public void setDetail(String detail) { this.detail = detail; }
}
