FROM node:22-alpine AS builder
WORKDIR /app

# npm registry for installs. The lockfile already pins registry.npmmirror.com
# tarball URLs; this keeps ad-hoc installs consistent and lets CI override the
# source without editing the Dockerfile.
ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org
ENV NPM_CONFIG_REGISTRY=${NPM_CONFIG_REGISTRY}

COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
