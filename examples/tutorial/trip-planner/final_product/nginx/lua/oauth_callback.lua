-- OAuth callback - exchanges code for tokens, creates session
local cjson = require("cjson")

local function generate_random_string(length)
    local f = io.open("/dev/urandom", "rb")
    if not f then return tostring(ngx.now()) end
    local bytes = f:read(length)
    f:close()
    local hex = ""
    for i = 1, #bytes do
        hex = hex .. string.format("%02x", string.byte(bytes, i))
    end
    return hex
end

local function url_encode(str)
    str = string.gsub(str, "([^%w%-%.%_%~])", function(c)
        return string.format("%%%02X", string.byte(c))
    end)
    return str
end

-- Validate state (CSRF)
local args = ngx.req.get_uri_args()
local state = args.state
local code = args.code
local error_param = args.error

if error_param then
    ngx.log(ngx.ERR, "OAuth error: ", error_param)
    return ngx.redirect("/login?error=" .. error_param)
end

if not state or not code then
    return ngx.redirect("/login?error=missing_params")
end

local states = ngx.shared.oauth_states
local state_data_str = states:get(state)
if not state_data_str then
    return ngx.redirect("/login?error=invalid_state")
end
states:delete(state)
local state_data = cjson.decode(state_data_str)

-- Exchange code for tokens
-- Use forwarded proto if behind a proxy, otherwise detect from request
local scheme = ngx.var.http_x_forwarded_proto or ngx.var.scheme
local host = ngx.var.host
if ngx.var.server_port ~= "80" and ngx.var.server_port ~= "443" then
    host = host .. ":" .. ngx.var.server_port
end
local redirect_uri = scheme .. "://" .. host .. "/auth/callback"

local body = "code=" .. ngx.escape_uri(code)
    .. "&client_id=" .. ngx.escape_uri(_G.GOOGLE_CLIENT_ID)
    .. "&client_secret=" .. ngx.escape_uri(_G.GOOGLE_CLIENT_SECRET)
    .. "&redirect_uri=" .. ngx.escape_uri(redirect_uri)
    .. "&grant_type=authorization_code"

local sock = ngx.socket.tcp()
sock:settimeout(10000)

local ok, err = sock:connect("oauth2.googleapis.com", 443)
if not ok then
    ngx.log(ngx.ERR, "Failed to connect to Google: ", err)
    return ngx.redirect("/login?error=token_exchange_failed")
end

local sess, err = sock:sslhandshake(false, "oauth2.googleapis.com", false)
if not sess then
    ngx.log(ngx.ERR, "SSL handshake failed: ", err)
    sock:close()
    return ngx.redirect("/login?error=ssl_failed")
end

local request = "POST /token HTTP/1.1\r\n"
    .. "Host: oauth2.googleapis.com\r\n"
    .. "Content-Type: application/x-www-form-urlencoded\r\n"
    .. "Content-Length: " .. #body .. "\r\n"
    .. "Connection: close\r\n"
    .. "\r\n"
    .. body

sock:send(request)

-- Read response
local status_line = sock:receive("*l")
if not status_line then
    sock:close()
    return ngx.redirect("/login?error=no_response")
end

-- Read headers
local headers = {}
local content_length = 0
while true do
    local line = sock:receive("*l")
    if not line or line == "" then break end
    local key, val = line:match("^(.-):%s*(.+)$")
    if key then
        headers[key:lower()] = val
        if key:lower() == "content-length" then
            content_length = tonumber(val) or 0
        end
    end
end

-- Read body
local response_body = ""
if headers["transfer-encoding"] == "chunked" then
    while true do
        local chunk_size_str = sock:receive("*l")
        if not chunk_size_str then break end
        local chunk_size = tonumber(chunk_size_str, 16)
        if not chunk_size or chunk_size == 0 then break end
        local chunk_data = sock:receive(chunk_size)
        if chunk_data then response_body = response_body .. chunk_data end
        sock:receive("*l")
    end
elseif content_length > 0 then
    response_body = sock:receive(content_length)
end
sock:close()

if not response_body or response_body == "" then
    return ngx.redirect("/login?error=empty_response")
end

local token_data = cjson.decode(response_body)
if not token_data or not token_data.access_token then
    ngx.log(ngx.ERR, "Token exchange failed: ", response_body)
    return ngx.redirect("/login?error=token_decode_failed")
end

-- Extract user info from ID token (JWT)
local id_token = token_data.id_token or ""
local user_email = "unknown@unknown.com"
local user_name = "User"

if id_token ~= "" then
    local payload_b64 = id_token:match("^[^.]+%.([^.]+)%.")
    if payload_b64 then
        -- Fix base64 padding
        local remainder = #payload_b64 % 4
        if remainder == 2 then payload_b64 = payload_b64 .. "=="
        elseif remainder == 3 then payload_b64 = payload_b64 .. "=" end
        payload_b64 = payload_b64:gsub("-", "+"):gsub("_", "/")

        local payload_json = ngx.decode_base64(payload_b64)
        if payload_json then
            local payload = cjson.decode(payload_json)
            if payload then
                user_email = payload.email or user_email
                user_name = payload.name or payload.given_name or user_email:match("^([^@]+)")
            end
        end
    end
end

-- Store refresh token in Redis (persistent)
local redis = require("resty.redis")
local red = redis:new()
red:set_timeout(5000)

local redis_ok, redis_err = red:connect(_G.REDIS_CONFIG.host, _G.REDIS_CONFIG.port)
if not redis_ok then
    ngx.log(ngx.ERR, "Redis connect failed: ", redis_err)
    return ngx.redirect("/login?error=redis_failed")
end

if _G.REDIS_CONFIG.password then
    red:auth(_G.REDIS_CONFIG.password)
end

-- Store refresh token persistently
if token_data.refresh_token then
    red:set("refresh_token:" .. user_email, cjson.encode({
        refresh_token = token_data.refresh_token,
        provider = "google",
        stored_at = ngx.time(),
    }))
else
    -- Check for existing refresh token
    local stored = red:get("refresh_token:" .. user_email)
    if stored and stored ~= ngx.null then
        local stored_data = cjson.decode(stored)
        token_data.refresh_token = stored_data.refresh_token
    else
        -- Force consent to get refresh token
        red:set_keepalive(10000, 100)
        return ngx.redirect("/auth/google?prompt=consent")
    end
end

-- Create session
local session_id = generate_random_string(32)
local session_data = cjson.encode({
    user_email = user_email,
    user_name = user_name,
    provider = "google",
    access_token = token_data.access_token,
    refresh_token = token_data.refresh_token,
    id_token = id_token,
    expires_at = ngx.time() + (token_data.expires_in or 3600),
    created_at = ngx.time(),
})

red:setex("session:" .. session_id, 2592000, session_data)  -- 30 days

ngx.log(ngx.INFO, "Session created for: ", user_email)

red:set_keepalive(10000, 100)

-- Set session cookie
ngx.header["Set-Cookie"] = "session_id=" .. session_id
    .. "; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000"

-- Redirect to dashboard
local redirect_to = state_data.redirect_to or "/"
return ngx.redirect(redirect_to)
