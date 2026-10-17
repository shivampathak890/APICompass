# ==============================================================================
# APICompass v3 - Frontend Dockerfile
# Lean Node.js container for Vite + React + Tailwind development & hackathon demo
# ==============================================================================

FROM node:20-alpine

WORKDIR /app

# Ensure non-root node user owns workspace
RUN chown -R node:node /app

# Install dependencies using locked versions
COPY --chown=node:node package.json package-lock.json ./
RUN npm ci

# Copy frontend source code and configuration
COPY --chown=node:node . .

USER node

EXPOSE 5173

# Native lightweight health check querying the Vite HTTP server
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:5173/ || exit 1

# Start Vite dev server bound to 0.0.0.0 for external browser access
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

