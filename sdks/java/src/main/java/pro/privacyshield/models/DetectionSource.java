package pro.privacyshield.models;

import com.fasterxml.jackson.annotation.JsonValue;

/**
 * PII detection source.
 */
public enum DetectionSource {
    REGEX("regex"),
    SLM("slm"),
    COMPOSITE("composite");

    private final String value;

    DetectionSource(String value) {
        this.value = value;
    }

    @JsonValue
    public String getValue() {
        return value;
    }

    public static DetectionSource fromValue(String value) {
        for (DetectionSource source : DetectionSource.values()) {
            if (source.value.equalsIgnoreCase(value)) {
                return source;
            }
        }
        return null;
    }
}
