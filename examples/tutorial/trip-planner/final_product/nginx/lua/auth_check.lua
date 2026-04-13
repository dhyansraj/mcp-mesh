-- Auth check - validates session, sets x-user-email header
local cjson = require("cjson")

-- DEV_MODE bypass
if _G.DEV_MODE then
    ngx.req.set_header("x-user-email", "demo@tripplanner.dev")
    return
end

-- Public routes (no auth needed)
local uri = ngx.var.uri
if uri == "/api/health" or uri == "/health" then
    return
end

-- Get session cookie
local cookie = ngx.var.cookie_session_id
if not cookie then
    return ngx.redirect("/login")
end

-- Validate session in Redis
local redis = require("resty.redis")
local red = redis:new()
red:set_timeout(5000)

local ok, err = red:connect(_G.REDIS_CONFIG.host, _G.REDIS_CONFIG.port)
if not ok then
    ngx.log(ngx.ERR, "Redis connect failed: ", err)
    return ngx.redirect("/login?error=redis_failed")
end

if _G.REDIS_CONFIG.password then
    red:auth(_G.REDIS_CONFIG.password)
end

local session_str, err = red:get("session:" .. cookie)
if not session_str or session_str == ngx.null then
    red:set_keepalive(10000, 100)
    return ngx.redirect("/login?error=session_expired")
end

local session = cjson.decode(session_str)
if not session or not session.user_email then
    red:set_keepalive(10000, 100)
    return ngx.redirect("/login?error=invalid_session")
end

-- Token refresh if expiring soon (within 30 minutes)
local now = ngx.time()
if session.expires_at and (session.expires_at - now) < 1800 and session.refresh_token then
    ngx.log(ngx.INFO, "Refreshing token for: ", session.user_email)

    local sock = ngx.socket.tcp()
    sock:settimeout(10000)
    local conn_ok = sock:connect("oauth2.googleapis.com", 443)
    if conn_ok then
        local ssl_ok = sock:sslhandshake(false, "oauth2.googleapis.com", false)
        if ssl_ok then
            local body = "refresh_token=" .. ngx.escape_uri(session.refresh_token)
                .. "&client_id=" .. ngx.escape_uri(_G.GOOGLE_CLIENT_ID)
                .. "&client_secret=" .. ngx.escape_uri(_G.GOOGLE_CLIENT_SECRET)
                .. "&grant_type=refresh_token"

            local request = "POST /token HTTP/1.1\r\n"
                .. "Host: oauth2.googleapis.com\r\n"
                .. "Content-Type: application/x-www-form-urlencoded\r\n"
                .. "Content-Length: " .. #body .. "\r\n"
                .. "Connection: close\r\n\r\n" .. body

            sock:send(request)
            local status_line = sock:receive("*l")

            -- Read headers
            local content_length = 0
            while true do
                local line = sock:receive("*l")
                if not line or line == "" then break end
                local key, val = line:match("^(.-):%s*(.+)$")
                if key and key:lower() == "content-length" then
                    content_length = tonumber(val) or 0
                end
            end

            if content_length > 0 then
                local resp_body = sock:receive(content_length)
                if resp_body then
                    local refresh_data = cjson.decode(resp_body)
                    if refresh_data and refresh_data.access_token then
                        session.access_token = refresh_data.access_token
                        session.expires_at = now + (refresh_data.expires_in or 3600)
                        if refresh_data.id_token then
                            session.id_token = refresh_data.id_token
                        end
                        red:setex("session:" .. cookie, 2592000, cjson.encode(session))
                        ngx.log(ngx.INFO, "Token refreshed for: ", session.user_email)
                    end
                end
            end
        end
        sock:close()
    end
end

-- Extend session TTL on activity
red:expire("session:" .. cookie, 2592000)
red:set_keepalive(10000, 100)

-- Set x-user-email header for downstream services
ngx.req.set_header("x-user-email", session.user_email)
