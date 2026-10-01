# Use an official Maven image with OpenJDK 17
FROM maven:3.8.4-openjdk-17-slim

# Set working directory
WORKDIR /app

# Copy the SDK source and pom.xml
COPY pom.xml .
COPY src ./src

# Install dependencies and build the SDK
RUN mvn clean install -DskipTests -e

# Environment variables (overridable at runtime)
ENV PS_API_KEY=""
ENV PS_BASE_URL="http://host.docker.internal:8000"

# Default command: compile and run Demo.java
ENTRYPOINT ["mvn", "exec:java", "-Dexec.mainClass=pro.privacyshield.Demo"]








