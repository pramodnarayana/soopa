FROM node:20-alpine

# Set working directory
WORKDIR /app

# Install pnpm and pm2 globally
RUN corepack enable pnpm
RUN npm install -g pm2

# Copy monorepo config files
COPY package.json pnpm-workspace.yaml turbo.json pnpm-lock.yaml ./

# Copy all packages and apps
# In a real enterprise setup, you would use `turbo prune` to optimize this,
# but since we want a "fat" container that can run either/both engines dynamically, we copy everything.
COPY packages ./packages
COPY server ./server

# Install dependencies
RUN pnpm install --frozen-lockfile

# Build everything
RUN pnpm build

# Expose ports for both engines
EXPOSE 3001
EXPOSE 3002

# Copy the pm2 config
COPY ecosystem.config.cjs ./

# By default, use pm2 to run the engines specified in the config
USER node
CMD ["pm2-runtime", "start", "ecosystem.config.cjs"]
