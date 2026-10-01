package pro.privacyshield.exceptions;

import pro.privacyshield.models.PrivacyShieldError;

/**
 * Exception thrown when the Privacy Shield API returns an error response.
 */
public class PrivacyShieldApiException extends PrivacyShieldException {
    private final int statusCode;
    private final String code;
    private final String detail;

    public PrivacyShieldApiException(int statusCode, PrivacyShieldError error) {
        super(error.getError());
        this.statusCode = statusCode;
        this.code = error.getCode();
        this.detail = error.getDetail();
    }

    public PrivacyShieldApiException(int statusCode, String message, String code, String detail) {
        super(message);
        this.statusCode = statusCode;
        this.code = code;
        this.detail = detail;
    }

    public int getStatusCode() { return statusCode; }
    public String getCode() { return code; }
    public String getDetail() { return detail; }

    @Override
    public String toString() {
        return "PrivacyShieldApiException{" +
                "statusCode=" + statusCode +
                ", code='" + (code != null ? code : "UNKNOWN") + '\'' +
                ", detail='" + (detail != null ? detail : "NONE") + '\'' +
                ", message='" + getMessage() + '\'' +
                '}';
    }
}
