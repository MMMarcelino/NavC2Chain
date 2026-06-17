FROM node:20-slim
WORKDIR /app
COPY package.json .
RUN npm install
COPY index.mjs .
EXPOSE 6000
CMD ["node", "index.mjs"]
