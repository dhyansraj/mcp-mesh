-- OAuth initiation - redirects to Google
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

local state = generate_random_string(16)
local redirect_to = ngx.var.arg_redirect or "/"

-- Store state for CSRF validation
local states = ngx.shared.oauth_states
states:set(state, cjson.encode({redirect_to = redirect_to}), 600)

-- Use forwarded proto if behind a proxy, otherwise detect from request
local scheme = ngx.var.http_x_forwarded_proto or ngx.var.scheme
local host = ngx.var.host
if ngx.var.server_port ~= "80" and ngx.var.server_port ~= "443" then
    host = host .. ":" .. ngx.var.server_port
end
local redirect_uri = scheme .. "://" .. host .. "/auth/callback"

local params = ngx.encode_args({
    client_id = _G.GOOGLE_CLIENT_ID,
    redirect_uri = redirect_uri,
    response_type = "code",
    scope = "openid email profile",
    state = state,
    access_type = "offline",
    prompt = ngx.var.arg_prompt or nil,
})

return ngx.redirect("https://accounts.google.com/o/oauth2/v2/auth?" .. params)
