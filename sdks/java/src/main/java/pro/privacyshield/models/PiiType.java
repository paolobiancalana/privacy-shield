package pro.privacyshield.models;

import com.fasterxml.jackson.annotation.JsonValue;

/**
 * PII entity type codes supported by Privacy Shield.
 */
public enum PiiType {
    PERSONA("pe"),
    ORGANIZZAZIONE("org"),
    LOCALITA("loc"),
    INDIRIZZO("ind"),
    MEDICO("med"),
    LEGALE("leg"),
    RELAZIONE("rel"),
    FINANZIARIO("fin"),
    PROFESSIONE("pro"),
    DATA_NASCITA("dt"),
    CODICE_FISCALE("cf"),
    IBAN("ib"),
    EMAIL("em"),
    TELEFONO("tel");

    private final String value;

    PiiType(String value) {
        this.value = value;
    }

    @JsonValue
    public String getValue() {
        return value;
    }

    public static PiiType fromValue(String value) {
        for (PiiType type : PiiType.values()) {
            if (type.value.equalsIgnoreCase(value)) {
                return type;
            }
        }
        return null;
    }
}
