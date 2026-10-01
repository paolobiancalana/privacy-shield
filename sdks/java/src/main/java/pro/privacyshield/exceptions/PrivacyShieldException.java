package pro.privacyshield.exceptions;

import pro.privacyshield.models.PrivacyShieldError;

/**
 * Base exception for all Privacy Shield SDK errors.
 */
public class PrivacyShieldException extends RuntimeException {
    public PrivacyShieldException(String message) {
        super(message);
    }

    public PrivacyShieldException(String message, Throwable cause) {
        super(message, cause);
    }
}


