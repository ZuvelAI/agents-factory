# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
FROM node:24.19.0-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS build
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN corepack enable
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/control-plane/package.json apps/control-plane/package.json
RUN pnpm install --frozen-lockfile
COPY apps/control-plane apps/control-plane
RUN pnpm --filter @agents-factory/control-plane build

FROM node:24.19.0-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/ZuvelAI/agents-factory" \
    org.opencontainers.image.revision="$SOURCE_REVISION" \
    org.opencontainers.image.title="Agents Factory Control Plane"
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000
RUN groupadd --system agents && useradd --system --gid agents --home /nonexistent agents
WORKDIR /app
COPY --from=build --chown=agents:agents /workspace/apps/control-plane/.next/standalone ./
COPY --from=build --chown=agents:agents /workspace/apps/control-plane/.next/static ./apps/control-plane/.next/static
COPY --from=build --chown=agents:agents /workspace/apps/control-plane/public ./apps/control-plane/public
USER agents:agents
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD ["node", "-e", "fetch('http://127.0.0.1:3000/health/ready').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
CMD ["node", "apps/control-plane/server.js"]
