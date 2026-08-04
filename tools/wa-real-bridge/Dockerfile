FROM node:20-slim

# Chromium + fonts for whatsapp-web.js/puppeteer (bridge.js already launches
# with --no-sandbox, required when running as root inside a container).
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium fonts-liberation ca-certificates libnss3-tools \
    && rm -rf /var/lib/apt/lists/*

# Trust any corporate/proxy root CAs dropped in certs/ (e.g. a Netskope-style
# TLS-intercepting proxy) so Chromium can reach real HTTPS hosts behind it.
# Safe to run with none present — build still succeeds without a certs/ folder.
RUN mkdir -p /usr/local/share/ca-certificates/extra/ \
    && if [ -d certs ] && ls certs/*.crt >/dev/null 2>&1; then \
         cp certs/*.crt /usr/local/share/ca-certificates/extra/; \
       fi \
    && update-ca-certificates

ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# Modern Chromium ignores the NSS/platform trust store by default in favor of
# its own built-in Chrome Root Store, so the imported corporate CA above would
# otherwise be silently ignored. This policy reverts to the platform verifier.
RUN mkdir -p /etc/chromium/policies/managed \
    && printf '{"ChromeRootStoreEnabled": false}' > /etc/chromium/policies/managed/policy.json

WORKDIR /usr/src/app

RUN groupadd -r pptruser && useradd -r -g pptruser -G audio,video pptruser \
    && mkdir -p /home/pptruser/Downloads \
    && chown -R pptruser:pptruser /home/pptruser /usr/src/app

# Chromium reads its own NSS cert DB, not /etc/ssl/certs, so the corporate
# CAs above also need importing here for the browser to trust them too.
RUN mkdir -p /home/pptruser/.pki/nssdb \
    && certutil -d sql:/home/pptruser/.pki/nssdb -N --empty-password \
    && for cert in /usr/local/share/ca-certificates/extra/*.crt; do \
         [ -f "$cert" ] && certutil -d sql:/home/pptruser/.pki/nssdb -A -t "C,," -n "$(basename "$cert" .crt)" -i "$cert"; \
       done; \
    chown -R pptruser:pptruser /home/pptruser/.pki

COPY --chown=pptruser:pptruser package*.json ./
RUN npm ci --omit=dev

COPY --chown=pptruser:pptruser bridge.js ./

USER pptruser

EXPOSE 3000
CMD ["node", "bridge.js"]
