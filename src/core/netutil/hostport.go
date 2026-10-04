// Package netutil builds network addresses and URLs from a host and a
// port in a way that is correct for IPv6 literals (issue #1604).
//
// `fmt.Sprintf("%s:%d", host, port)` turns `::1` into `::1:8080`,
// which neither `net.Dial` nor `url.Parse` can split back into a host
// and a port. These helpers bracket IPv6 literals, and tolerate a host
// that already arrives bracketed (`[::1]`) so that form keeps working
// rather than becoming `[[::1]]:8080`.
package netutil

import (
	"net"
	"strconv"
)

// JoinHostPort returns host:port, bracketing an IPv6 literal host.
func JoinHostPort(host string, port int) string {
	return net.JoinHostPort(Unbracket(host), strconv.Itoa(port))
}

// BaseURL returns scheme://host:port with no trailing slash, bracketing an
// IPv6 literal host.
func BaseURL(scheme, host string, port int) string {
	return scheme + "://" + JoinHostPort(host, port)
}

// Unbracket strips the brackets from a bracketed IPv6 literal ("[::1]"
// becomes "::1") and returns any other host unchanged, so hosts can be
// compared in one form whichever way they were written.
func Unbracket(host string) string {
	if len(host) >= 2 && host[0] == '[' && host[len(host)-1] == ']' {
		return host[1 : len(host)-1]
	}
	return host
}

// DialableHost maps a bind-style host to one a peer can dial. An empty
// host or an unspecified address (0.0.0.0, ::, [::]) means "every
// interface" to a listener but is not an address anyone else can reach,
// so it becomes localhost — correct for the single-machine setup where an
// agent advertises its bind address. Any other host is returned unchanged.
func DialableHost(host string) string {
	if host == "" {
		return "localhost"
	}
	if ip := net.ParseIP(Unbracket(host)); ip != nil && ip.IsUnspecified() {
		return "localhost"
	}
	return host
}
