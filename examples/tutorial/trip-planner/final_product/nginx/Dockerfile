FROM openresty/openresty:alpine

RUN apk add --no-cache perl curl && opm get ledgetech/lua-resty-http && apk del perl curl

# Copy nginx config
ARG NGINX_CONF=nginx.conf
COPY ${NGINX_CONF} /usr/local/openresty/nginx/conf/nginx.conf

# Copy Lua scripts
COPY lua/ /etc/nginx/lua/
RUN chmod -R 755 /etc/nginx/lua/

# Create html directory (UI dist is mounted via docker-compose volume)
RUN mkdir -p /usr/share/nginx/html

EXPOSE 80

CMD ["openresty", "-g", "daemon off;"]
