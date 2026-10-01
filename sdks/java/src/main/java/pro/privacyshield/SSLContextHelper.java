package pro.privacyshield;

import javax.net.ssl.KeyManagerFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManagerFactory;
import java.io.ByteArrayInputStream;
import java.security.KeyFactory;
import java.security.KeyStore;
import java.security.PrivateKey;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.security.spec.PKCS8EncodedKeySpec;
import java.util.Base64;

/**
 * Utility to create SSLContext from PEM strings (mTLS).
 */
public class SSLContextHelper {

    public static SSLContext createSSLContext(String clientCertPem, String clientKeyPem, String caCertPem) throws Exception {
        // 1. Load Client Certificate
        CertificateFactory cf = CertificateFactory.getInstance("X.509");
        X509Certificate cert = (X509Certificate) cf.generateCertificate(
                new ByteArrayInputStream(clientCertPem.getBytes()));

        // 2. Load Private Key (assuming PKCS#8)
        String privateKeyContent = clientKeyPem
                .replace("-----BEGIN PRIVATE KEY-----", "")
                .replace("-----END PRIVATE KEY-----", "")
                .replaceAll("\\s", "");
        byte[] encoded = Base64.getDecoder().decode(privateKeyContent);
        PKCS8EncodedKeySpec keySpec = new PKCS8EncodedKeySpec(encoded);
        KeyFactory kf = KeyFactory.getInstance("RSA");
        PrivateKey privateKey = kf.generatePrivate(keySpec);

        // 3. Create KeyStore
        KeyStore keyStore = KeyStore.getInstance(KeyStore.getDefaultType());
        keyStore.load(null, null);
        keyStore.setKeyEntry("client-key", privateKey, "".toCharArray(), new java.security.cert.Certificate[]{cert});

        KeyManagerFactory kmf = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
        kmf.init(keyStore, "".toCharArray());

        // 4. Load CA (TrustManager)
        TrustManagerFactory tmf = null;
        if (caCertPem != null) {
            X509Certificate caCert = (X509Certificate) cf.generateCertificate(
                    new ByteArrayInputStream(caCertPem.getBytes()));
            KeyStore trustStore = KeyStore.getInstance(KeyStore.getDefaultType());
            trustStore.load(null, null);
            trustStore.setCertificateEntry("ca-cert", caCert);
            tmf = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
            tmf.init(trustStore);
        }

        // 5. Create SSLContext
        SSLContext sslContext = SSLContext.getInstance("TLS");
        sslContext.init(kmf.getKeyManagers(), (tmf != null ? tmf.getTrustManagers() : null), null);
        return sslContext;
    }
}
