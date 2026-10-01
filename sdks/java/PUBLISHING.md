# Privacy Shield Java SDK - Publishing Guide

This guide explains how to publish the Java SDK to **Maven Central** using the new **Sonatype Central Portal**.

## Prerequisites

1. **Sonatype Account**: Create an account at [central.sonatype.com](https://central.sonatype.com/).
2. **Namespace Verification**: 
   - Once logged in, go to **Publish > Namespaces**.
   - Add `pro.privacyshield`.
   - Verify ownership (usually via a DNS TXT record on your domain `privacyshield.pro`).
3. **GPG Installed**: You must have `gpg` installed on your Mac (`brew install gnupg`).

---

## Step 1: Generate GPG Key

Maven Central requires all artifacts to be signed.

1. Generate a key:
   ```bash
   gpg --generate-key
   ```
   *Follow the prompts. Use your name and `biancalana.paolo@gmail.com`.*

2. List your key to get the ID:
   ```bash
   gpg --list-keys
   ```
   *Copy the long hexadecimal ID (last 8 or more characters).*

3. Publish your public key to a keyserver (so Sonatype can verify it):
   ```bash
   gpg --keyserver keys.openpgp.org --send-keys YOUR_KEY_ID
   ```

---

## Step 2: Generate Sonatype User Token

1. In the [Central Portal](https://central.sonatype.com/), click your username (top right) > **View User Tokens**.
2. Click **Generate User Token**.
3. Copy the **Username** and **Password** (these are NOT your login credentials, they are unique tokens for Maven).

---

## Step 3: Configure Local `settings.xml`

Edit (or create) your Maven settings file at `~/.m2/settings.xml`:

```xml
<settings>
  <servers>
    <server>
      <id>central</id>
      <username>TOKEN_USERNAME</username>
      <password>TOKEN_PASSWORD</password>
    </server>
  </servers>
</settings>
```

---

## Step 4: Deploy

From the `sdks/java` directory, run:

```bash
mvn clean deploy -Dgpg.passphrase=YOUR_GPG_PASSWORD
```

### What This Command Does:
1. **Compiles** the code and runs tests.
2. **Generates** the standard JAR.
3. **Generates** a `-sources.jar` (the source code).
4. **Generates** a `-javadoc.jar` (the documentation).
5. **Signs** everything with your GPG key.
6. **Uploads** the package to the Sonatype Portal.

---

## Step 5: Finalize in Portal

1. Go to **Publish > Deployments** in the Central Portal.
2. You should see your upload. If all validations pass (green), click **Publish**.
3. Within 30-60 minutes, your SDK will be available on the Central Repository!
