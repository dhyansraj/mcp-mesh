-- Logout - clears session
local cjson = require("cjson")

local cookie = ngx.var.cookie_session_id
if cookie then
    local redis = require("resty.redis")
    local red = redis:new()
    red:set_timeout(5000)

    local ok = red:connect(_G.REDIS_CONFIG.host, _G.REDIS_CONFIG.port)
    if ok then
        if _G.REDIS_CONFIG.password then
            red:auth(_G.REDIS_CONFIG.password)
        end
        red:del("session:" .. cookie)
        red:set_keepalive(10000, 100)
    end
end

-- Clear cookie
ngx.header["Set-Cookie"] = "session_id=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"

return ngx.redirect("/")
