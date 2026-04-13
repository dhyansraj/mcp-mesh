-- Returns current user session info
local cjson = require("cjson")

-- DEV_MODE
if _G.DEV_MODE then
    ngx.header["Content-Type"] = "application/json"
    ngx.say(cjson.encode({
        authenticated = true,
        email = "demo@tripplanner.dev",
        name = "Demo User",
        dev_mode = true,
    }))
    return
end

local cookie = ngx.var.cookie_session_id
if not cookie then
    ngx.header["Content-Type"] = "application/json"
    ngx.say(cjson.encode({authenticated = false}))
    return
end

local redis = require("resty.redis")
local red = redis:new()
red:set_timeout(5000)

local ok = red:connect(_G.REDIS_CONFIG.host, _G.REDIS_CONFIG.port)
if not ok then
    ngx.header["Content-Type"] = "application/json"
    ngx.say(cjson.encode({authenticated = false, error = "redis_unavailable"}))
    return
end

if _G.REDIS_CONFIG.password then
    red:auth(_G.REDIS_CONFIG.password)
end

local session_str = red:get("session:" .. cookie)
red:set_keepalive(10000, 100)

if not session_str or session_str == ngx.null then
    ngx.header["Content-Type"] = "application/json"
    ngx.say(cjson.encode({authenticated = false}))
    return
end

local session = cjson.decode(session_str)
ngx.header["Content-Type"] = "application/json"
ngx.say(cjson.encode({
    authenticated = true,
    email = session.user_email,
    name = session.user_name,
    provider = session.provider,
}))
