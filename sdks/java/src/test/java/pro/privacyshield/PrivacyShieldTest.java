package pro.privacyshield;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import pro.privacyshield.models.*;

import java.util.Arrays;
import java.util.Collections;

import static org.junit.jupiter.api.Assertions.*;

public class PrivacyShieldTest {

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    public void testTokenizeRequestSerialization() throws Exception {
        TokenizeRequest request = new TokenizeRequest(
                Arrays.asList("Hello world"),
                "org-123",
                "req-456",
                Collections.singletonMap("pii", "token")
        );

        String json = mapper.writeValueAsString(request);
        assertTrue(json.contains("\"texts\":[\"Hello world\"]"));
        assertTrue(json.contains("\"organization_id\":\"org-123\""));
        assertTrue(json.contains("\"request_id\":\"req-456\""));
        assertTrue(json.contains("\"existing_tokens\":{\"pii\":\"token\"}"));
    }

    @Test
    public void testTokenizeResponseDeserialization() throws Exception {
        String json = "{" +
                "\"tokenized_texts\":[\"Hello [token]\"]," +
                "\"tokens\":[{" +
                "  \"token\":\"[token]\"," +
                "  \"original\":\"world\"," +
                "  \"type\":\"pe\"," +
                "  \"start\":6," +
                "  \"end\":11," +
                "  \"source\":\"regex\"" +
                "}]," +
                "\"detection_ms\":10.5," +
                "\"tokenization_ms\":15.2" +
                "}";

        TokenizeResponse response = mapper.readValue(json, TokenizeResponse.class);
        assertEquals(1, response.getTokenizedTexts().size());
        assertEquals("Hello [token]", response.getTokenizedTexts().get(0));
        assertEquals(1, response.getTokens().size());
        assertEquals(PiiType.PERSONA, response.getTokens().get(0).getType());
        assertEquals(DetectionSource.REGEX, response.getTokens().get(0).getSource());
        assertEquals(10.5, response.getDetectionMs());
    }

    @Test
    public void testPiiTypeEnum() {
        assertEquals("pe", PiiType.PERSONA.getValue());
        assertEquals(PiiType.PERSONA, PiiType.fromValue("pe"));
        assertEquals(PiiType.PERSONA, PiiType.fromValue("PE"));
    }

    @Test
    public void testConfigBuilder() {
        PrivacyShieldConfig config = PrivacyShieldConfig.builder()
                .apiKey("test-key")
                .baseUrl("https://test.api/")
                .build();

        assertEquals("test-key", config.getApiKey());
        assertEquals("https://test.api", config.getBaseUrl());
    }

    @Test
    public void testConfigMissingApiKey() {
        assertThrows(IllegalStateException.class, () -> {
            PrivacyShieldConfig.builder().build();
        });
    }
}
