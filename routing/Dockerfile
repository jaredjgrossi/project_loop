# GraphHopper has no official image, so run the official release jar on a plain JRE.
FROM eclipse-temurin:21-jre

ARG GRAPHHOPPER_VERSION=11.1
ADD --checksum=sha256:8462f758d9ea49edaded557cec5c687a0a24f004ec371cd4daaeb0534824ea33 \
    https://github.com/graphhopper/graphhopper/releases/download/${GRAPHHOPPER_VERSION}/graphhopper-web-${GRAPHHOPPER_VERSION}.jar \
    /graphhopper/graphhopper-web.jar

WORKDIR /graphhopper
EXPOSE 8989
# Config and map data are mounted by docker-compose.yml.
ENTRYPOINT ["java", "-Xms512m", "-Xmx2g", "-jar", "graphhopper-web.jar", "server", "/config/config.yml"]
