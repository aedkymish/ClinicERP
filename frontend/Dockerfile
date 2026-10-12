FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund --fetch-retries=6 --fetch-timeout=600000
COPY . .
# Rewrites are resolved at build time: point /api/v1 at the compose "api" service
ARG API_URL=http://api:8000
ENV NEXT_TELEMETRY_DISABLED=1 API_URL=${API_URL}
RUN npm run build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
